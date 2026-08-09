"""Pointers to shared ingest stages (orchestrated via agents.ingest wrappers)."""

# Implementations remain in app.agents.ingest.* so Agent registry stays stable.
# New connector code must not import those agents — only AcquiredFile + pipeline job.
CONNECT = "app.agents.ingest.connect.ConnectAgent"
FINGERPRINT = "app.agents.ingest.fingerprint.FingerprintAgent"
PARSE = "app.agents.ingest.parse.ParseAgent"
CLEANSTACK = "app.agents.ingest.cleanstack.CleanStackAgent"
CHUNK = "app.agents.ingest.chunk.ChunkAgent"
WEAVER = "app.agents.ingest.weaver.GraphWeaverAgent"
EMBED = "app.agents.ingest.embed.EmbedAgent"
HEALTH = "app.agents.ingest.health.IndexHealthAgent"
