"""Ephemeral SSH keypair generation for eval sessions.

Each eval session generates a fresh Ed25519 keypair:
  - Public key → injected into sandbox container's authorized_keys
  - Private key → passed to harness container as env var / file mount

No passwords. Keys are discarded when the session tears down.
"""

from __future__ import annotations

import subprocess
import tempfile
import os
from dataclasses import dataclass


@dataclass
class SSHKeyPair:
    """An ephemeral SSH keypair."""
    private_key: str  # PEM-encoded private key
    public_key: str   # OpenSSH-format public key (one line)


def generate_keypair() -> SSHKeyPair:
    """Generate an ephemeral Ed25519 SSH keypair.

    Uses ssh-keygen (available on all Linux/macOS systems).
    Keys exist only in memory after generation.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "id_ed25519")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-q", "-C", "eval-session"],
            check=True,
            capture_output=True,
        )
        private_key = open(key_path).read()
        public_key = open(f"{key_path}.pub").read().strip()

    return SSHKeyPair(private_key=private_key, public_key=public_key)
