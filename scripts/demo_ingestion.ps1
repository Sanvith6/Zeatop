# === Zeatop Signal Ingestion Demo ===

Write-Host ""
Write-Host "=== Step 1: JWT Token Obtained ===" -ForegroundColor Green
$body = @{username="sre-intern"; password="zeotap-local"} | ConvertTo-Json
$token = (Invoke-RestMethod -Uri "http://localhost:8000/api/auth/token" -Method Post -Body $body -ContentType "application/json").access_token
Write-Host "Token: $($token.Substring(0,30))..."

Write-Host ""
Write-Host "=== Step 2: Sending Signal to POST /api/signals ===" -ForegroundColor Green
$signal = @{
    component_id   = "DEMO_SERVER_01"
    component_type = "api"
    severity       = "P1"
    error_message  = "Connection refused on port 443"
    timestamp      = [System.DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json
Write-Host "Request Body:"
Write-Host $signal

Write-Host ""
Write-Host "=== Step 3: Response (HTTP 202 Accepted) ===" -ForegroundColor Green
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/signals" -Method Post -Body $signal -ContentType "application/json" -Headers @{Authorization="Bearer $token"}
$response | ConvertTo-Json
