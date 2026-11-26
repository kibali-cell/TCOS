# Data sovereignty: where data is stored and who can reach it

Owner principle: know where sensitive data is stored and who can access it.
The live version of the "who" part is the **Access review** screen (Administration menu,
needs permission to view the audit log). This page is the written companion.

## Where data lives

| Kind of data | Class | Stored | On phones and computers |
|---|---|---|---|
| Child profiles, welfare cases, medical records, education records | Child-sensitive | Central PostgreSQL database only | **Never cached** (D-H1) |
| Financial records, approval requests, TZS limits | Financial | Central database | Encrypted drafts only, from Slice 10 |
| Staff personal records | Staff personal | Central database | Not cached |
| Donor records | Confidential | Central database | Not cached |
| Users, roles, permissions, audit log | Internal | Central database (audit log append-only) | Some reference data encrypted, from Slice 10 |
| Passwords | Secret | Argon2id hashes in the database; never logged or audited | Never |
| Uploaded files | Per record | Private storage, served only through permission-checked endpoints (Slice 7) | Not cached |

No sensitive data is stored in browser storage, URLs, logs or the service-worker cache (CLAUDE.md rules 7 and 13).

## Hosting region: not decided

The region where the database runs is **an open owner decision** (SCHEMA section 9, item 11). It decides which country's law applies to the data and how fast Shinga can reach it. The Access review screen says "not decided" until the setting `TCOS_HOSTING_REGION` is filled in. Please also confirm the Tanzania Personal Data Protection Act review (item 10) before real child records are entered.

## Who can reach what

1. **Inside the application:** only people whose roles grant it, within their scope. Access is the union of a person's roles, checked on the server for every request. `is_superuser` grants nothing. Out-of-scope records appear not to exist.
2. **Granting access:** sensitive roles need a second person's approval (D-065). Nobody can grant a role to themselves. The one exception is the server console (D-071), which is audited.
3. **Seeing it:** the Access review screen lists, for each kind of data, the people who can reach it, with scope and role, plus every sensitive role and its holders. Opening it is itself audited.

## What the application cannot protect

- Whoever runs the database server or hosting account can read the stored data and the backups.
- Anyone with the database owner password can read and change every table. The server runs as a restricted role (`tcos_app`) so a bug in the application cannot alter the audit log or approval history, but the owner can.
- The audit hash chain shows tampering; it cannot stop a database superuser from doing it.
- Backups must be encrypted and kept to the same standard as the live database. No backup procedure is built yet.

Keep the database owner password and server access with the institution, not with one individual (CLAUDE.md section 1).

## Uploaded files (Slice 7)

Uploaded files are **not** in the database. They are stored on the server's disk in the private file store (`TCOS_PRIVATE_STORAGE_ROOT`; in Docker the named volume `tcos_private_files`), so they live wherever the server lives (hosting region: not yet decided). They are not encrypted at rest by the application: protect them with disk encryption on the host, and **include the volume in backups** (a database backup alone does not contain them). Files are served only to signed-in people allowed to see the record they belong to, and every upload and download is audited. Two-factor secrets are encrypted in the database with `TCOS_ENCRYPTION_KEY`; keep that key separately from database backups.

