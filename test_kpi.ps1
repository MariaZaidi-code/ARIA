Write-Host "=== Login ==="
$body = '{"username":"admin","password":"admin123"}'
try {
  $loginResp = Invoke-WebRequest -Uri 'http://localhost:8000/api/auth/login' -Method POST -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5
  $loginData = $loginResp.Content | ConvertFrom-Json
  $token = $loginData.token
  Write-Host "Login OK"
} catch {
  # Try register first
  try {
    $regBody = '{"username":"admin","email":"admin@test.com","password":"admin123"}'
    Invoke-WebRequest -Uri 'http://localhost:8000/api/auth/register' -Method POST -Body $regBody -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5 | Out-Null
    $loginResp = Invoke-WebRequest -Uri 'http://localhost:8000/api/auth/login' -Method POST -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5
    $loginData = $loginResp.Content | ConvertFrom-Json
    $token = $loginData.token
    Write-Host "Login OK (after register)"
  } catch {
    Write-Host "Login failed: $($_.Exception.Message)"
    return
  }
}

$headers = @{Authorization = "Bearer $token"}

Write-Host ""
Write-Host "=== Schema Summary ==="
try {
  $resp = Invoke-WebRequest -Uri 'http://localhost:8000/api/schema/summary' -Headers $headers -UseBasicParsing -TimeoutSec 5
  Write-Host "Status: $($resp.StatusCode)"
  Write-Host "Body: $($resp.Content.Substring(0, [Math]::Min(500, $resp.Content.Length)))"
} catch {
  $sr = $_.Exception.Response
  if ($sr) {
    $reader = New-Object System.IO.StreamReader($sr.GetResponseStream())
    Write-Host "Error: $($sr.StatusCode) - $($reader.ReadToEnd())"
  } else {
    Write-Host "Error: $($_.Exception.Message)"
  }
}

Write-Host ""
Write-Host "=== KPIs ==="
try {
  $resp2 = Invoke-WebRequest -Uri 'http://localhost:8000/api/data/kpis' -Headers $headers -UseBasicParsing -TimeoutSec 10
  Write-Host "Status: $($resp2.StatusCode)"
  Write-Host "Body: $($resp2.Content.Substring(0, [Math]::Min(1000, $resp2.Content.Length)))"
} catch {
  $sr = $_.Exception.Response
  if ($sr) {
    $reader = New-Object System.IO.StreamReader($sr.GetResponseStream())
    Write-Host "Error: $($sr.StatusCode) - $($reader.ReadToEnd())"
  } else {
    Write-Host "Error: $($_.Exception.Message)"
  }
}
