# Security Policy

## Scope

This project runs on an ESP32-S3 and provides a local HTTP dashboard. It is not designed to be exposed directly to the public internet.

## Supported versions

Only the latest revision on the default branch is expected to receive security-related fixes.

## Sensitive information

Never publish:

- T3 KYS passwords;
- Wi-Fi passwords;
- session cookies or authentication tokens;
- personal application data;
- generated `t3_*.json` files containing private information.

The dashboard does not provide a separate web login layer. Use the application only on a trusted local network and do not port-forward it to the internet.

## Reporting

For a suspected security issue, avoid posting credentials or exploitable details in a public issue. Contact the project maintainer through the repository's available private contact method.
