"""Docker network management for isolated eval sessions.

Each miner evaluation gets its own Docker network (eval_net). The sandbox and
harness containers attach to this network. The validator container does NOT
attach — it communicates with eval containers only via Docker API.
"""

from __future__ import annotations

import logging
import secrets

import docker
from docker.models.networks import Network

logger = logging.getLogger(__name__)


class NetworkManager:
    """Creates and tears down isolated Docker networks for eval sessions."""

    def __init__(self, client: docker.DockerClient, prefix: str = "eval"):
        self.client = client
        self.prefix = prefix

    def create(self, session_id: str | None = None) -> Network:
        """Create an isolated bridge network for one eval session.

        Returns a Docker Network object. Containers are attached via
        network.connect(container) or by passing network= at creation.
        """
        if session_id is None:
            session_id = secrets.token_hex(6)

        name = f"{self.prefix}_{session_id}"

        # Internal=True means no outbound routing from the network by default.
        # Harness egress is punched through via iptables rules on the harness
        # container, not on the network itself.
        network = self.client.networks.create(
            name=name,
            driver="bridge",
            internal=True,  # no default egress
            labels={
                "trajectoryrl.role": "eval_net",
                "trajectoryrl.session": session_id,
            },
            # Prevent IP conflicts by letting Docker assign subnets
            check_duplicate=True,
        )
        logger.info("Created eval network %s (id=%s)", name, network.short_id)
        return network

    def destroy(self, network: Network) -> None:
        """Remove a network. Disconnects any remaining containers first."""
        try:
            # Disconnect stragglers (shouldn't happen in normal flow)
            network.reload()
            for container_info in (network.attrs.get("Containers") or {}).values():
                cname = container_info.get("Name", "unknown")
                logger.warning("Disconnecting straggler %s from %s", cname, network.name)
                try:
                    network.disconnect(cname, force=True)
                except docker.errors.APIError:
                    pass
            network.remove()
            logger.info("Removed eval network %s", network.name)
        except docker.errors.NotFound:
            logger.debug("Network %s already removed", network.name)
        except docker.errors.APIError as e:
            logger.error("Failed to remove network %s: %s", network.name, e)

    def cleanup_stale(self, max_age_hours: int = 24) -> int:
        """Remove old eval networks that were never cleaned up.

        Returns count of networks removed.
        """
        removed = 0
        for net in self.client.networks.list(
            filters={"label": "trajectoryrl.role=eval_net"}
        ):
            # TODO: check creation time vs max_age_hours once we store timestamps
            # For now, just log — manual cleanup via `docker network prune`
            logger.debug("Found stale eval network: %s", net.name)
        return removed
