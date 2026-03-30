$ports = @(8502, 8503, 8504, 8505, 8506, 8507, 8508, 8509, 8510)
foreach ($port in $ports) {
    $procId = (netstat -ano | Select-String ":$port " | Select-String "LISTENING") -replace '.*\s+(\d+)$','$1'
    if ($procId -match '^\d+$') {
        Write-Host "Killing PID $procId on port $port"
        Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "Done"
