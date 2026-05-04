# Deployment

This document collects optional deployment notes. The main project can run locally with `python start_web.py`; the steps below are only for users who want a long-running server setup.

## Generic Server Notes

1. Clone the repository.
2. Create a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Copy `.env.example` to `.env` and fill in your own API keys.
5. Start the service with `python start_web.py`.

The app listens on `127.0.0.1:8080` by default. For public access, put it behind a reverse proxy and add authentication or firewall restrictions.

## Windows Server Helper

For Windows Server, an optional helper script is provided:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/iamzhangg/wxarticle/master/deploy_windows.ps1 | iex
```

The script installs dependencies, pulls the latest code, creates a virtual environment, and registers a scheduled task named `wxarticle`.

After first deployment, edit:

```text
C:\wxarticle\.env
```

Then restart the scheduled task:

```powershell
schtasks /run /tn wxarticle
```

## GitHub Actions

The workflow in `.github/workflows/daily.yml` is optional. To use it, configure repository secrets for the API keys required by your chosen generation mode.
