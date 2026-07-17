# Azure Deployment Notes

## App Service Startup Command

Set the following startup command in the Azure Portal:

```
gunicorn --bind=0.0.0.0 --timeout 600 run:app
```

**Where to set it:**
Azure Portal → Your App Service → **Configuration** → **General settings** tab →
**Startup Command** field → paste the command → **Save**.

This is a Portal/CLI setting, not a file in the repository. It must be set manually
after creating the App Service, or via the Azure CLI:

```bash
az webapp config set \
  --resource-group <rg-name> \
  --name <app-name> \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 600 run:app"
```

## Required App Service Environment Variables

Set these under **Configuration → Application settings**:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Strong random string for Flask session signing |
| `DB_HOST` | Azure MySQL Flexible Server hostname |
| `DB_USER` | MySQL username |
| `DB_PASSWORD` | MySQL password |
| `DB_NAME` | Database name (e.g. `vaccination_db`) |
| `DB_SSL_REQUIRED` | Set to `true` to enable SSL for Azure MySQL |
| `ESP32_AUTH_TOKEN` | Shared secret for ESP32 hardware authentication |
| `AT_API_KEY` | Africa's Talking API key |
| `AT_USERNAME` | Africa's Talking username |
| `AT_SENDER_ID` | Africa's Talking sender ID |
| `ACS_CONNECTION_STRING` | Azure Communication Services connection string |
| `MAIL_SENDER` | Sender email address for ACS email |

## Scale-out Warning

**Run this App Service as a single instance only.**
The APScheduler reminder jobs run inside the Flask process. Scaling out to multiple
instances would cause each instance to independently fire the same reminder jobs,
resulting in duplicate SMS/email sends to guardians. If scale-out is needed in the
future, move the scheduler to a dedicated worker process before enabling it.
