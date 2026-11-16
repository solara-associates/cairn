/* R3-08: a userspace egress-blocking shim.
 *
 * This repository runs on a dev workstation with no root and a CI runner
 * (GitHub Actions `ubuntu-latest`) also with no assumed root/CAP_NET_ADMIN
 * -- confirmed before writing this (`sudo -n true` fails, no `unshare`
 * binary present on the dev machine). A real network namespace or
 * firewall rule is therefore not available in both places this unit must
 * actually run and prove the block in. This file is the one concrete,
 * testable mechanism this unit settled on instead: a dynamic-library
 * shim, loaded into the sandboxed child process only
 * (`LD_PRELOAD`/`DYLD_INSERT_LIBRARIES`, set only in
 * `cairn_adapters.sandbox_runner.runner`'s own child environment, never
 * the parent's), that intercepts libc's own `connect()` and refuses any
 * destination that is not loopback or a local Unix-domain socket.
 *
 * This is a real interception of the actual syscall-adjacent libc entry
 * point every TCP/UDP client in the process (whatever language it is
 * written in -- `make`, `npm`, `cargo`, `pytest`, a raw `curl`) ultimately
 * calls to originate an outbound connection, not a cooperative check a
 * sandboxed process could choose to skip. It is deny-by-default: anything
 * that is not loopback/AF_UNIX is refused with ECONNREFUSED, there is no
 * allow-list to misconfigure open.
 *
 * Two platform-specific interception mechanisms, because the dev loop
 * (macOS) and CI (Linux) need different ones:
 *
 * - Linux (`LD_PRELOAD`): the dynamic linker's own symbol search order
 *   already lets a preloaded library's exported `connect` symbol take
 *   priority over libc's, for any normal (non-static, non-setuid)
 *   dynamically linked binary -- no special macro needed. The real libc
 *   implementation is still reachable via `dlsym(RTLD_NEXT, "connect")`
 *   for the loopback/AF_UNIX pass-through case.
 * - macOS (`DYLD_INSERT_LIBRARIES`): dyld's flat-namespace symbol lookup
 *   does not reliably override already-bound libSystem symbols the same
 *   way; the supported way to replace a libc entry point here is
 *   `DYLD_INTERPOSE` (an Apple-documented macro using the dynamic
 *   linker's `__DATA,__interpose` section). A call made *from this same
 *   shim* to the plain `connect` symbol is not re-intercepted by
 *   `DYLD_INTERPOSE` (interposition only rewrites calls made by *other*
 *   images), so the loopback/AF_UNIX pass-through can call the real
 *   `connect` directly, with no `dlsym` needed on this platform.
 *
 * Known, deliberately accepted gap, documented rather than hidden: macOS
 * strips `DYLD_INSERT_LIBRARIES` for hardened-runtime/SIP-protected Apple
 * system binaries (e.g. the system `/usr/bin/curl`), so on macOS this
 * shim only covers non-hardened children (Python, Node, Cargo-built
 * binaries, Homebrew tools). This gap does not exist on Linux (this
 * project's actual deployment/CI target): `LD_PRELOAD` interposition is
 * not stripped for ordinary dynamically linked ELF binaries there, which
 * is what `cairn_adapters.sandbox_runner`'s own tests prove (see
 * `packages/adapters/tests/test_sandbox_runner.py`'s network-egress
 * test, run through the real Python child process the sandboxed "tests"
 * adapter would exec).
 */

#include <sys/socket.h>
#include <netinet/in.h>
#include <errno.h>
#include <string.h>

static int cairn_is_allowed(const struct sockaddr *addr) {
    if (addr == NULL) {
        return 1;
    }
    if (addr->sa_family == AF_INET) {
        const struct sockaddr_in *a = (const struct sockaddr_in *)addr;
        const unsigned char *b = (const unsigned char *)&a->sin_addr;
        return b[0] == 127; /* 127.0.0.0/8 */
    }
    if (addr->sa_family == AF_INET6) {
        const struct sockaddr_in6 *a = (const struct sockaddr_in6 *)addr;
        static const unsigned char loopback[16] = {
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
        };
        return memcmp(&a->sin6_addr, loopback, 16) == 0;
    }
    /* AF_UNIX and anything else (e.g. AF_UNSPEC used by some disconnect
     * calls): not a network egress path, always allowed. */
    return 1;
}

#if defined(__APPLE__)

#include <stdio.h>

#define CAIRN_DYLD_INTERPOSE(_replacement, _replacee)                                   \
    __attribute__((used)) static struct {                                               \
        const void *replacement;                                                        \
        const void *replacee;                                                           \
    } _cairn_interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = {   \
        (const void *)(unsigned long)&(_replacement),                                   \
        (const void *)(unsigned long)&(_replacee),                                      \
    };

static int cairn_connect(int sockfd, const struct sockaddr *addr, socklen_t addrlen) {
    if (!cairn_is_allowed(addr)) {
        fprintf(stderr, "cairn-sandbox: blocked outbound connect() (no network egress by default)\n");
        errno = ECONNREFUSED;
        return -1;
    }
    return connect(sockfd, addr, addrlen);
}

CAIRN_DYLD_INTERPOSE(cairn_connect, connect)

#else /* Linux / other ELF platforms: plain LD_PRELOAD symbol override */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

typedef int (*cairn_real_connect_fn)(int, const struct sockaddr *, socklen_t);

int connect(int sockfd, const struct sockaddr *addr, socklen_t addrlen) {
    if (!cairn_is_allowed(addr)) {
        fprintf(stderr, "cairn-sandbox: blocked outbound connect() (no network egress by default)\n");
        errno = ECONNREFUSED;
        return -1;
    }
    static cairn_real_connect_fn real_connect = NULL;
    if (real_connect == NULL) {
        real_connect = (cairn_real_connect_fn)dlsym(RTLD_NEXT, "connect");
    }
    return real_connect(sockfd, addr, addrlen);
}

#endif
