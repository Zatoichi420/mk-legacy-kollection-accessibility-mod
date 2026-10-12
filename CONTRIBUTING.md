# Contributing to MK Legacy Kollection Accessibility Mod

Thank you for your interest in contributing to this project! We welcome contributions from the community to help make this accessibility mod better for everyone.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally
3. **Create a new branch** for your feature or fix
4. **Make your changes** and test thoroughly
5. **Commit with clear messages** describing your changes
6. **Push to your fork** and **submit a pull request**

## Development Setup

You need Windows 10/11 64-bit and Python 3.12 (the Windows OCR bindings,
`winsdk`, have no wheels for newer Pythons). Testing against the real game
also needs Mortal Kombat Legacy Kollection and, ideally, NVDA.

```
py -3.12 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.12 -m pytest tests                 # unit tests (most also run on macOS/Linux)
py -3.12 ocr_reader\main.py --dev        # run the reader from source, F2 captures screens
py -3.12 packaging\build.py              # program + Setup.exe (needs Inno Setup 6) in dist\
py -3.12 packaging\ci\smoke_test.py      # checks the built program and installer
```

The README's "For developers" section explains how to add a screen to the
recognition library. Every new or changed screen entry needs hand-verified
`canonical_text`; raw OCR is never spoken from the library. Run the tests
afterwards: they fail if two screens are similar enough to be confused.

Accessibility rules for any change that affects what's spoken: failures
must be announced, never silent; every user action (hotkey, Start menu
entry) must produce something audible; and a selection must be spoken as
text, never left to colour alone.

`docs/PROGRESS.md` is the project's full development history. Read it
before reworking anything fundamental, because several obvious-looking
approaches (hooking Dear ImGui, OCR-only reading) were tried and abandoned
for documented reasons.

## Code of Conduct

- Be respectful and inclusive to all contributors
- Provide constructive feedback
- Report issues professionally
- No harassment or discrimination

## Types of Contributions

We welcome:
- **Bug reports** - Issues affecting functionality or accessibility
- **Feature requests** - Suggestions for new accessibility improvements
- **Code contributions** - Bug fixes and feature implementations
- **Documentation** - Improvements to README, guides, and comments
- **Testing** - Help testing the mod on different systems

## Reporting Bugs

When reporting bugs, please include:
- A clear description of the issue
- Steps to reproduce the problem
- Expected vs. actual behavior
- Screenshots or error messages (if applicable)
- Your system information (OS, game version, mod version)

## Pull Request Process

1. Ensure your code follows the project's style conventions
2. Update documentation and README if needed
3. Add or update tests for your changes (if applicable)
4. Provide a clear description of what your PR addresses
5. Link any related issues using `#issue-number`
6. Keep PRs focused on a single feature or fix

## Questions or Need Help?

- Open an issue to discuss ideas before starting major work
- Comment on existing issues if you have questions
- Be patient - maintainers will respond when able

## License

By contributing to this project, you agree that your contributions will be licensed under the same license as the project.

Thank you for helping make this project better! 🎮♿
