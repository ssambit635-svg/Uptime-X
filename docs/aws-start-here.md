# AWS after merge — start here

## What you need to do now

**Nothing in AWS yet.** The current PR delivers the application, local monitoring workers, tests and
infrastructure code. Reviewing or merging it does not create AWS resources, require AWS credentials
or spend AWS credits. GitHub Actions tests the code/containers and validates Terraform without
running an AWS plan/apply. Vercel is not the regional monitoring backend.

The owner approved this order on 19 November 2026:

1. Finish and test all pre-AWS implementation work.
2. Open/review/merge its PR.
3. Then guide the owner through account safety, a cost-reviewed staging deployment and live tests.

No deployment, regional AWS execution or real SQS DLQ/replay test has been claimed as passed.

## About the credit shown in your new account

If your AWS console shows $100 in credits, **do not treat that as a guaranteed spending cap or proof
this whole stack is free**. Check your own account's plan, credit eligibility, expiry and billing rules
in the console. This repository does not verify credit entitlement, eligible services or final bills.
We will review those together before starting anything paid; do not change account plans or enable
paid services merely to get past a setup screen without understanding the consequences.

The provided two-region staging design includes NAT gateways, an HTTPS load balancer, a database,
containers, logs and other resources. Some incur charges even with zero traffic. Importantly,
`enable_services=false` stops application tasks/schedules, **not** the network/database/load-balancer
costs. Budget alerts notify you; they are not a hard spending cap. No exact price or month of operation
within $100 is promised. Do not run `terraform apply` blindly.

## The guided steps after merge

We will take these one at a time, with the owner controlling the account:

1. **Secure the account:** protect the root login with MFA, review billing/credit settings, and use
   a limited operator identity or short-lived role for normal work rather than root access keys.
2. **Agree on costs first:** choose an approved test spending limit and time window, set billing alerts,
   review a current estimate for both regions, and identify who will stop/delete resources afterward.
   If the design does not fit the available credit, keep the working local demo and revise the AWS
   deployment plan explicitly before provisioning; do not silently weaken security or add charges.
3. **Configure deployment access safely:** prefer short-lived SSO/OIDC access. Never paste AWS access
   keys, session tokens, passwords, recovery codes or private Terraform state into chat or Git.
   Non-secret region names, role identifiers and sanitized errors are enough for setup discussion.
4. **Prepare account prerequisites:** state storage, approved regions and a domain/HTTPS certificate.
   An existing domain may be used; buying a domain is a separate decision, not an automatic step.
5. **Review the plan before creating resources:** inspect the exact account, region, IAM permissions,
   resource list and cost implications. The infrastructure code is not a one-click free-tier promise.
6. **Deploy and test a time-boxed staging environment:** build/scan a digest-pinned image, bootstrap
   private database access, enable the services and run actual checks from both regions.
7. **Prove failure handling and clean up:** run controlled retry/DLQ/replay/alarm drills only against
   owned test resources, verify restoration, then stop or delete the approved staging resources and
   account for retained snapshots/secrets. Only then record Phase 2's cloud acceptance as complete.

The advanced commands and evidence checklist live in the [operations runbook](operations.md).
Do not start with those commands before the account, costs and plan are reviewed together.

## What is left in the product roadmap?

After Phases 1 and 2 close, **four product phases remain**:

- Phase 3 — Incident intelligence.
- Phase 4 — Playground.
- Phase 5 — Recovery Lab.
- Phase 6 — Production polish.

The deployment/live verification above is remaining Phase 2 work, not a new roadmap phase.
