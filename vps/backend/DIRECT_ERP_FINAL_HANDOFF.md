# Direct Connect — consolidated Sandbox release handoff

## Verified evidence
- GitHub Actions at d579596e79669deef9a7d527e726e8a0caa41ac9: offline release gate, static site validation, isolated Sandbox rehearsal and Direct ERP reminder/selection tests all succeeded.
- Operator VPS output confirmed the guard-only sidecar and reviewed updater timer, empty encrypted vault provisioning, local recovery rehearsal, SHA256 match of the laptop recovery copy, and local daily encrypted snapshot timer.
- These checks do not establish real LHDN issuer identity, independent host recovery, real email delivery or production submission.

## One server preparation command (no provider or email activity)
Run as myradmin in the existing VPS checkout:
```bash
cd ~/myr-invoices && git fetch origin direct-erp-sidecar-rehearsal && git show 2ae4baeab84d0f6cac47eb62294a3595baca86a1:vps/stage-direct-reminder-scheduler.sh | bash -s -- --stage-disabled
```
This stages the exact reviewed reminder runtime and disabled timer. It does not enable the timer, write a grant, change the live auth gateway or send email. An already staged installation must be inspected rather than overwritten.

## External release gates
1. Recover the encrypted key from the laptop copy on an independent trusted host using the separately retained passphrase. Verify synthetic encrypted-record restore; configure protected offsite snapshots, retention and outbox recovery. Do not copy the raw key or passphrase into source or chat.
2. Obtain one actual authorized Sandbox company owner and verified provider issuer binding. The current direct sidecar is hard-disabled. OAuth plus public TIN lookup is not binding. A separate reviewed release must enforce scoped grant, native authentication, owner consent, distributed throttling, revocation and rotation before accepting credentials. No silent Easy/Direct fallback or mode switch.
3. Deploy and test the independently gated Sandbox reminder mail event and explicitly opted-in verified owner schedule. Preserve existing account mail behavior. The job must remain disabled without a valid opt-in grant.
4. Exercise a real Sandbox submission and trusted receipt polling. Only a matching Valid status with verified identifiers may supply the QR payload. Sandbox must not update production records. Production routing, signing, provider authorization and rollback must be reviewed separately.

## Release decision
The code is an offline-tested candidate, not a completed production release. Keep PR #14 draft; do not merge or publish automatically while activation and recovery gates remain open. No further repetitive synthetic tests are required merely to restate the existing evidence; any new test must cover a specific new change or missing acceptance requirement.
