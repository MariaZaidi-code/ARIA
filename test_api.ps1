Write-Host "=== Testing Backend ==="
try {
  $resp = Invoke-WebRequest -Uri 'http://localhost:8000/api/schema/summary' -UseBasicParsing -TimeoutSec 5
  Write-Host "Schema Summary Status: $($resp.StatusCode)"
  Write-Host "Schema Summary Body: $($resp.Content.Substring(0, [Math]::Min(800, $resp.Content.Length)))"
} catch {
  Write-Host "Schema Summary Error: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== Testing KPI Endpoint ==="
try {
  $resp2 = Invoke-WebRequest -Uri 'http://localhost:8000/api/data/kpis' -UseBasicParsing -TimeoutSec 5
  Write-Host "KPIs Status: $($resp2.StatusCode)"
  Write-Host "KPIs Body: $($resp2.Content.Substring(0, [Math]::Min(800, $resp2.Content.Length)))"
} catch {
  $sr = $_.Exception.Response
  if ($sr) {
    $reader = New-Object System.IO.StreamReader($sr.GetResponseStream())
    $body = $reader.ReadToEnd()
    Write-Host "KPIs Error Status: $($sr.StatusCode) ($([int]$sr.StatusCode))"
    Write-Host "KPIs Error Body: $body"
  } else {
    Write-Host "KPIs Error: $($_.Exception.Message)"
  }
}

Write-Host ""
Write-Host "=== Testing Suggestions Endpoint ==="
try {
  $resp3 = Invoke-WebRequest -Uri 'http://localhost:8000/api/suggestions' -Method POST -Body '{"limit":5}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5
  Write-Host "Suggestions Status: $($resp3.StatusCode)"
  Write-Host "Suggestions Body: $($resp3.Content.Substring(0, [Math]::Min(800, $resp3.Content.Length)))"
} catch {
  $sr = $_.Exception.Response
  if ($sr) {
    $reader = New-Object System.IO.StreamReader($sr.GetResponseStream())
    $body = $reader.ReadToEnd()
    Write-Host "Suggestions Error Status: $($sr.StatusCode) ($([int]$sr.StatusCode))"
    Write-Host "Suggestions Error Body: $body"
  } else {
    Write-Host "Suggestions Error: $($_.Exception.Message)"
  }
}
