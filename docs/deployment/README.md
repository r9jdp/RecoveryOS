# RecoveryOS legacy VM deployment

> [!WARNING]
> This OCI/Docker deployment design is retired and is not part of the supported runtime. Current
> development uses Supabase PostgreSQL and Temporal Cloud. A replacement Python-service hosting
> target must be selected before these legacy deployment documents and scripts are removed.

RecoveryOS uses a deliberately small free-tier topology:

```text
Vercel Hobby (Next.js)
        |
        | HTTPS
        v
Oracle Ampere A1 VM
  Caddy edge (one instance)
    |-- staging API + customer agent
    `-- production API + customer agent
        |-- Neon staging/production branches
        `-- Temporal Cloud staging/production namespaces
```

The continuously running API, Temporal worker, and customer-agent containers live
on the OCI VM. The browser receives only public API origins and never payment,
database, Temporal, telephony, or signing secrets.

## What is automated

- OCI network and ARM VM creation through Terraform.
- Initial Docker, firewall, deploy-user, and directory setup through cloud-init.
- Linux/ARM64 image builds for API, worker, and customer agent.
- Shared Caddy TLS routing for both environments.
- Compose deployment, readiness smoke checks, and image-tag rollback.

## What remains a credentialed/manual prerequisite

- An OCI account with available Always Free Ampere capacity.
- A Neon project with isolated staging and production branches/roles.
- Two Temporal Cloud namespaces and their scoped credentials.
- Four DNS records for API and customer-agent origins.
- A Vercel project and its public frontend environment variables.
- GitHub repository/package permissions and GHCR authentication on the VM.

No cloud resource has been provisioned merely because its template is present in
the repository. Follow the runbooks in this directory and record evidence for
each phase gate.

## Go/no-go gate

Phase 0 is **GO** only when all of the following are true:

- OCI reports the VM as `RUNNING`, cloud-init completed, and the VM remains in
  the account's current free-eligible allocation.
- DNS resolves all four origins to the VM and Caddy has issued certificates.
- Staging and production use different Neon branches/roles.
- Staging and production use different Temporal namespaces and task queues.
- `GET /health/live` and `GET /health/ready` succeed through public HTTPS.
- Vercel serves the frontend and calls only the staging API during validation.
- The VM can pull private GHCR packages with a read-only credential.
- No provider secret is present in Vercel browser variables, an image layer, the
  repository, or deployment output.

Phase 0 is **NO-GO** if Ampere capacity cannot be obtained, the account shows a
non-zero forecast, either environment shares data/workflow credentials, or a
readiness check cannot authenticate to its dependency. Do not silently replace
the worker with a service that sleeps; pause for an explicit hosting decision.

## Runbook index

- [OCI provisioning](./oci.md)
- [Neon setup](./neon.md)
- [Temporal Cloud setup](./temporal-cloud.md)
- [Vercel setup](./vercel.md)
- [Secret handling](./secrets.md)
- [Build, deploy, smoke, and rollback](./runbook.md)
- [Health endpoint contract](./health.md)
