# Railway Volume File Upload Workflow

## Problem
Need to upload local files to a Railway volume when Railway CLI doesn't have a direct upload command.

## Solution Overview
Use Google Drive (or similar file host) as an intermediary, then download directly into the Railway container.

---

## Step-by-Step Process

### 1. Install Railway CLI (if needed)
```powershell
npm install -g @railway/cli
```

**If command not found after install:**
- Run `npm config get prefix` to find npm global path
- Add that path to Windows PATH environment variable
- Restart PowerShell

### 2. Prepare Your Files
- Compress files into a zip archive
- Upload to Google Drive (or file.io, WeTransfer, etc.)
- **Important:** Set Google Drive sharing to "Anyone with the link"

### 3. Get the Direct Download Link
For Google Drive, convert the share link:
```
Original: https://drive.google.com/file/d/FILE_ID/view?usp=sharing
Convert to: https://drive.google.com/uc?export=download&id=FILE_ID
```

### 4. SSH into Railway Container
```powershell
railway ssh --project=PROJECT_ID --environment=ENV_ID --service=SERVICE_ID
```

Or if already linked to project:
```powershell
railway shell
```

### 5. Download Files in Container
```bash
# Navigate to target directory
cd /app/data/LidarPt

# Download the file
wget --no-check-certificate 'https://drive.google.com/uc?export=download&id=FILE_ID' -O files.zip

# Extract
unzip files.zip

# Verify
ls -la

# Clean up (optional)
rm files.zip
```

### 6. Exit Container
```bash
exit
```

---

## Troubleshooting

### "Command not found" for railway
- Check if npm global directory is in PATH
- Try using `npx @railway/cli` instead
- Restart PowerShell after PATH changes

### Download gets HTML instead of file
- File isn't publicly accessible on Google Drive
- Make sure sharing is set to "Anyone with the link"
- Try alternative: Use `gdown` tool or different file host

### Unzip error "not a zipfile"
- Downloaded file is corrupted or is HTML login page
- Verify download: `file files.zip`
- Re-check sharing permissions and try again

---

## Alternative File Hosts
If Google Drive causes issues, use these instead:
- **file.io** - One-time download, no account needed
- **WeTransfer** - Simple, reliable
- **transfer.sh** - Command-line friendly

---

## Quick Reference Commands

```powershell
# Check Railway volume
railway volume list

# SSH into container
railway shell

# Inside container
cd /app/data/LidarPt
wget URL -O files.zip
unzip files.zip
ls -la
exit
```