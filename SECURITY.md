# Security and private data

Keep account credentials, ESPHome API keys, mesh credentials and network keys
private. The published examples contain blank connection constants. Store
configured copies outside the repository or in the ignored `local/` directory.
An edited public `app_*.py` file is still included in a source distribution;
clear its personal values before publication.

Ignore rules do not remove files already tracked by Git or protect an
indiscriminate ZIP of a working folder. Inspect both release archives and Git
history. If credentials have been exposed, rotate them and remove the private
data from published artifacts as appropriate.

The cloud example masks common authentication fields, but names, account IDs
and device addresses remain visible. Review output before sharing it.

Report vulnerabilities privately to the repository maintainer. Do not include
passwords, network keys or private account records in a public issue.
