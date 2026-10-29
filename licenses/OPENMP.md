# OpenMP runtime corresponding source

Ollama's official Linux archive contains libgomp.so.1.0.0 (SHA-256 e985bcbb6b444c2c472de70c331ab101e6de860affa3a20d1d1aecd06d9242e8). It matches byte-for-byte the library in AlmaLinux libgomp-8.5.0-28.el8_10.alma.1.x86_64.rpm, obtained from https://repo.almalinux.org/almalinux/8/BaseOS/x86_64/os/Packages/.

The complete corresponding GCC source RPM, including distribution patches and build instructions, is included in the bundle at third-party-sources/gcc-8.5.0-28.el8_10.alma.1.src.rpm. It was obtained from https://vault.almalinux.org/8.10/BaseOS/Source/Packages/gcc-8.5.0-28.el8_10.alma.1.src.rpm. The source hash is pinned in release-inputs.json. GPL-3.0.txt and GCC-RUNTIME-LIBRARY-EXCEPTION.txt retain the library's license terms. No changes were made to the distributed library.
