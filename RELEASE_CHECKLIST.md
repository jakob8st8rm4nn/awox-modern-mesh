# Publication checklist

Before publishing a release:

- Check documentation links, example filenames and command signatures against
  the current source.
- Run the offline suite from the repository root.
- Check the separate ESPHome dependency test and record the resolved versions.
- Build the wheel and source distribution; inspect their file lists.
- Install the wheel in a separate environment and check its public imports.
- Run the offline suite from the extracted source distribution.
- Keep connection constants blank in all 29 public examples.
- Exclude local credentials, notes, captures, reports, caches and build output.
- For a manual source ZIP, exclude `__pycache__/` and `*.pyc` explicitly;
  a folder compression tool does not necessarily apply `.gitignore`.
- Check the version, changelog, MIT license and package metadata.
- Add project URLs and a private security contact once the repository is created.
- Review Git history as well as the working tree for private data.

See [Offline tests](documentation/TESTING.md) for commands and
[Security](SECURITY.md) for handling local credentials.
