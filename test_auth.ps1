Write-Host "=== Login ==="
$body = '{"username":"admin","password":"admin123"}'
$loginResp = Invoke-WebRequest -Uri 'http://localhost:8000/api/auth/login' -Method POST -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5
$loginData = $loginResp.Content | ConvertFrom-Json
$token = $loginData.token
Write-Host "Token: $($token.Substring(0, [Math]::Min(30, $token.Length)))..."

Write-Host ""
Write-Host "=== Schema Summary ==="
$headers = @{Authorization = "Bearer $token"}
$resp = Invoke-WebRequest -Uri 'http://localhost:8000/api/schema/summary' -Headers $headers -UseBasicParsing -TimeoutSec 5
Write-Host "Status: $($resp.StatusCode)"
Write-Host "Body: $($resp.Content.Substring(0, [Math]::Min(1000, $resp.Content.Length)))"

Write-Host ""
Write-Host "=== KPIs ==="
$resp2 = Invoke-WebRequest -Uri 'http://localhost:8000/api/data/kpis' -Headers $headers -UseBasicParsing -TimeoutSec 5
Write-Host "Status: $($resp2.StatusCode)"
Write-Host "Body: $($resp2.Content.Substring(0, [Math]::Min(1000, $resp2.Content.Length)))"
