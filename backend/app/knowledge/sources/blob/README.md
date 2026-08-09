# Azure Blob connector

Lists and downloads blobs into `AcquiredFile` for the shared ingest pipeline.

## Enable

Set one of:

```env
VERA_AZURE_BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
```

Optional:

```env
VERA_AZURE_STORAGE_ACCOUNT=myaccount
VERA_AZURE_STORAGE_KEY=...
```

Restart `vera-api`. `GET /api/sources/connectors` should show `blob.state: "configured"`.

## API

`POST /api/sources/blob` with `{ "workspace_id", "container", "prefix?": "" }`.

Until the Azure SDK download path is wired, a configured instance still returns a clear error if list/download is not implemented; unconfigured instances return `501 BLOB_NOT_CONFIGURED`.
