# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0]

### Added
- Intelligent parsing and diffing of YAML content within multiline strings (literal blocks with `|`)
- Color-coded output showing additions (green), deletions (red), and modifications (yellow)
- Support for Python 3.8 through 3.14
- Smart list sorting to avoid false differences due to ordering
- Improved handling of multiline YAML strings in diff output
- Fixed CI pipeline compatibility issues
- Enhanced output format for better readability of complex YAML structures
