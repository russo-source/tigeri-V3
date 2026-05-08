# Tigeri AWS deploy kit (existing S3 Express bucket + EC2)

Wires this repo into your existing AWS resources:

| Resource | Value |
|---|---|
| S3 Express bucket | `trigeri--global--use1-az4--x-s3` |
| Region | `us-east-1` |
| AWS account | `596871238695` |
| EC2 instance | `i-0018214267e351749` (`ec2-100-48-88-95.compute-1.amazonaws.com`) |
| EC2 OS | Amazon Linux 2023 |
| Key pair | `tigeri_global` |

Note: this is an **S3 Express One Zone (Directory) bucket** — the IAM policy uses the `s3express:` ARN namespace and grants `s3express:CreateSession` in addition to standard object actions. boto3 ≥ 1.35 routes Directory bucket names to the right endpoint automatically.

## One-time IAM setup (run on your laptop with admin AWS creds)

```bash
export TIGERI_S3_DOCUMENTS_BUCKET=trigeri--global--use1-az4--x-s3
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=596871238695

cd infra/aws/deploy
chmod +x setup_iam.sh attach_profile.sh deploy.sh setup_remote.sh
./setup_iam.sh                                  # creates tigeri-app-role + tigeri-app-profile
./attach_profile.sh i-0018214267e351749         # attaches profile to the EC2 instance
```

The instance profile grants the EC2 host `s3express:CreateSession` plus `s3:Get/Put/Delete/ListBucket` on the directory bucket, and `logs:*` on CloudWatch. No static AWS keys are stored on the instance.

## One-time EC2 prep (on the host, as root)

After the first `deploy.sh` run (which copies `infra/aws/deploy/` into `/tmp/tigeri-staged/`):

```bash
sudo bash /tmp/tigeri-staged/infra/aws/deploy/setup_remote.sh
sudo $EDITOR /etc/tigeri/tigeri.env            # set ANTHROPIC_API_KEY, DB URL, etc.
sudo systemctl start tigeri-api
```

The systemd unit (`tigeri-api.service`) runs uvicorn under user `tigeri` from `/opt/tigeri/.venv`, reading config from `/etc/tigeri/tigeri.env`.

## Recurring deploys (laptop)

```bash
EC2_HOST=ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com \
SSH_KEY=~/.ssh/tigeri_global.pem \
./deploy.sh
```

`deploy.sh` rsyncs the repo, installs deps inside the venv, runs `alembic upgrade head`, and restarts the service.

## What the app sees

- `boto3.client("s3", region_name="us-east-1")` uses the instance role automatically.
- The bucket name comes from `TIGERI_S3_DOCUMENTS_BUCKET` in `/etc/tigeri/tigeri.env`.
- The Invoice Agent inbox accepts `s3://bucket/key`, `s3:bucket:key`, and bare keys (resolved against the default bucket). See [src/tigeri/agents/invoice/adapters/s3.py](../../../src/tigeri/agents/invoice/adapters/s3.py).
- For S3 Directory buckets, `put_document` skips the `ServerSideEncryption` parameter (the bucket auto-encrypts with SSE-S3 and rejects the explicit param).
