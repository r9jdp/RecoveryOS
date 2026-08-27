# OCI Always Free host provisioning

The Terraform module creates an Ampere A1 VM, VCN, public subnet, internet
gateway, route table, and narrowly scoped security rules. It defaults to 2 OCPUs,
12 GiB RAM, and a 50 GiB boot volume. Confirm those values are free eligible in
the target tenancy before applying; eligibility and capacity are account- and
region-dependent.

## Prerequisites

1. Install Terraform and the OCI CLI locally.
2. Configure OCI API-key authentication in the standard OCI config file. Never
   put an API private key in `terraform.tfvars`.
3. Obtain the tenancy and target compartment OCIDs.
4. Create a dedicated SSH Ed25519 key and identify the operator's current public
   IPv4 `/32`. The module rejects unrestricted SSH.
5. Check Ampere A1 capacity in each availability domain in the intended region.

## Plan before apply

Run from the repository root:

```bash
cd infra/oci/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check
terraform validate
terraform plan -out=recoveryos.tfplan
```

Review the plan in the OCI console context. It should create one compute instance
and networking resources only. Do not apply if the console's cost estimator or
tenancy limits indicate a charge.

Apply only after review:

```bash
terraform apply recoveryos.tfplan
terraform output public_ip
terraform output -raw ssh_command
```

If A1 capacity is unavailable, change `availability_domain_index` to another
valid index and plan again. If every domain is unavailable, the Phase 0 decision
is NO-GO; retain the plan and wait or request a budget decision.

## First-login verification

Cloud-init may take several minutes after the instance reports `RUNNING`:

```bash
ssh recoveryos@VM_PUBLIC_IP
cloud-init status --wait
docker version
docker compose version
sudo ufw status verbose
findmnt /var/lib/docker
```

Expected ingress is TCP 22 from the operator CIDR, TCP 80/443 from the internet,
and UDP 443 for HTTP/3. PostgreSQL, Temporal, API, and agent container ports must
not be exposed on the host.

## DNS and stable origins

Create DNS `A` records pointing to the Terraform `public_ip` output:

```text
api.example.com
agent.example.com
staging-api.example.com
staging-agent.example.com
```

The assigned address is stable while this VM/VNIC exists, but it is not a
separately reserved address. Recreating the instance can change it; update DNS
and verify TLS before traffic is restored. Use low TTLs during initial setup.

## Host hardening checklist

- Disable SSH password and root login after confirming key access.
- Keep SSH restricted to the operator CIDR in both OCI and UFW.
- Enable OCI account MFA and least-privilege policies.
- Confirm unattended security updates are active.
- Never add a public bind for ports 8000, 8010, 5432, or 7233.
- Treat membership in the `docker` group as root-equivalent.
- Export Terraform state to an encrypted private location; state can contain
  infrastructure metadata even though this module receives no cloud secrets.
