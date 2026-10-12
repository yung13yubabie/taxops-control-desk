# Security and data handling

Do not publish customer records, tax documents, credentials, private keys, database
files, backups, personal screenshots, or private development conversations in this
repository, issues, pull requests, or CI artifacts. Tests should create synthetic
data in isolated temporary directories. Diagnostic uploads must contain only
synthetic data and reviewed technical metadata.

## Reporting

Do not paste a suspected secret or customer record into a public report. Use a
previously verified private contact with the repository maintainer, or GitHub's
private vulnerability reporting option if it is available. Do not assume that
private reporting has been enabled. Send only the minimum redacted description
needed to establish a secure reporting channel.

## Suspected exposure

Stop publishing the affected material and preserve needed evidence privately.
Have the credential owner revoke or rotate confirmed exposed credentials through
the official provider. Do not test credentials against live services. Review the
scope privately, including reachable history, releases, artifacts, and clones.

A new commit that untracks a file does not erase history. History rewriting,
force-pushes, credential changes, release deletion, and GitHub Support requests
are separate operations requiring explicit authorization and coordination.
Copies in forks, clones, pull requests, or cached views may remain even after a
history rewrite. No local scanner proves that all historical copies are clean.

## Prevention and scope

The repository hygiene check rejects prohibited tracked paths, nonempty environment
templates, and selected high-confidence credential markers without logging their
values. It is defense in depth, not a complete secret or personal-data scanner.
Review staged diffs and asset provenance before publishing. Consider GitHub secret
scanning/push protection where supported; this policy does not enable or change
repository security settings.

References:
- [GitHub: Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
