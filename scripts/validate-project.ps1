#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$DagId = "kubeshop_batch_analytics",
    [int]$HttpTimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$bigDataComposeFile = Join-Path $repoRoot "docker-compose.bigdata.yml"

foreach ($file in @($composeFile, $bigDataComposeFile)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        Write-Error "Fichier requis introuvable : $file"
        exit 1
    }
}

$dockerCommand = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $dockerCommand) {
    Write-Error "Docker CLI est introuvable dans PATH."
    exit 1
}

$dockerPath = [string]$dockerCommand.Path
$composeArguments = @(
    "compose",
    "--project-directory", $repoRoot,
    "-f", $composeFile,
    "-f", $bigDataComposeFile
)
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $ArgumentList) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Impossible de démarrer la commande."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdoutTask.GetAwaiter().GetResult().Trim()
            StdErr = $stderrTask.GetAwaiter().GetResult().Trim()
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-ComposeCommand {
    param([Parameter(Mandatory)][string[]]$Arguments)
    Invoke-NativeCommand -FilePath $dockerPath -ArgumentList ($composeArguments + $Arguments)
}

function Assert-NativeSuccess {
    param(
        [Parameter(Mandatory)][object]$Result,
        [Parameter(Mandatory)][string]$Label
    )
    if ($Result.ExitCode -ne 0) {
        $message = if (-not [string]::IsNullOrWhiteSpace($Result.StdErr)) {
            $Result.StdErr
        }
        elseif (-not [string]::IsNullOrWhiteSpace($Result.StdOut)) {
            $Result.StdOut
        }
        else {
            "Aucun détail disponible."
        }
        if ($message.Length -gt 1000) {
            $message = $message.Substring(0, 1000) + "..."
        }
        throw "$Label a échoué (code $($Result.ExitCode)) : $message"
    }
}

function Invoke-ValidationCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    try {
        $details = & $Action
        if ($details -is [array]) {
            $details = $details -join "; "
        }
        if ([string]::IsNullOrWhiteSpace([string]$details)) {
            $details = "Validation réussie."
        }
        [void]$results.Add([pscustomobject]@{
            Statut = "PASS"
            Test = $Name
            Details = [string]$details
        })
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
    catch {
        [void]$results.Add([pscustomobject]@{
            Statut = "FAIL"
            Test = $Name
            Details = $_.Exception.Message
        })
        Write-Host "[FAIL] $Name" -ForegroundColor Red
    }
}

Write-Host "`nValidation finale de KubeShop`n" -ForegroundColor Cyan

Invoke-ValidationCheck -Name "Configuration Docker Compose combinée" -Action {
    $result = Invoke-ComposeCommand -Arguments @("config", "--quiet")
    Assert-NativeSuccess -Result $result -Label "docker compose config"
    "Les deux fichiers Compose sont valides."
}

Invoke-ValidationCheck -Name "Les 11 services attendus sont actifs" -Action {
    $expectedServices = @(
        "airflow", "analytics-dashboard", "auth-service", "cassandra",
        "event-service", "frontend", "kafka", "payment-service",
        "postgres", "redis", "stream-processor"
    )
    $result = Invoke-ComposeCommand -Arguments @("ps", "--services", "--status", "running")
    Assert-NativeSuccess -Result $result -Label "docker compose ps"
    $runningServices = @(
        $result.StdOut -split "\r?\n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    $missingServices = @($expectedServices | Where-Object { $_ -notin $runningServices })
    if ($missingServices.Count -gt 0) {
        throw "Services absents ou arrêtés : $($missingServices -join ', ')"
    }
    if ($runningServices.Count -ne $expectedServices.Count) {
        throw "Nombre de services actifs inattendu : $($runningServices.Count)."
    }
    "$($runningServices.Count) services actifs."
}

$httpEndpoints = @(
    @{ Name = "Auth API"; Uri = "http://localhost:3001/health" },
    @{ Name = "Payment API"; Uri = "http://localhost:3002/health" },
    @{ Name = "Event API"; Uri = "http://localhost:3003/health" },
    @{ Name = "Frontend"; Uri = "http://localhost:8080/health" },
    @{ Name = "Airflow"; Uri = "http://localhost:8081/health" },
    @{ Name = "Tableau de bord"; Uri = "http://localhost:8082/" }
)

foreach ($endpoint in $httpEndpoints) {
    Invoke-ValidationCheck -Name "HTTP 200 - $($endpoint.Name)" -Action {
        $response = Invoke-WebRequest -Uri $endpoint.Uri -Method Get -TimeoutSec $HttpTimeoutSeconds -UseBasicParsing
        if ([int]$response.StatusCode -ne 200) {
            throw "Statut HTTP obtenu : $($response.StatusCode)"
        }
        if ($endpoint.Name -eq "Airflow") {
            $health = $response.Content | ConvertFrom-Json
            if ($health.scheduler.status -ne "healthy") {
                throw "Le scheduler Airflow n'est pas healthy."
            }
        }
        "$($endpoint.Uri) retourne HTTP 200."
    }
}

$requiredOutputFiles = @(
    "data/output/daily_sales.csv",
    "data/output/weekly_sales.csv",
    "data/output/monthly_sales.csv",
    "data/output/product_metrics.csv",
    "data/output/dashboard_kpis.csv",
    "data/output/dashboard_summary.json",
    "data/output/product_analytics.csv",
    "data/output/recommendations.csv"
)

foreach ($relativePath in $requiredOutputFiles) {
    Invoke-ValidationCheck -Name "Sortie BI - $relativePath" -Action {
        $fullPath = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Fichier introuvable."
        }
        $item = Get-Item -LiteralPath $fullPath
        if ($item.Length -le 0) {
            throw "Le fichier est vide."
        }
        if ($item.Extension -eq ".csv") {
            $rows = @(Import-Csv -LiteralPath $fullPath)
            if ($rows.Count -eq 0) {
                throw "Le fichier CSV ne contient aucune ligne de données."
            }
            "$($rows.Count) ligne(s), $($item.Length) octets."
        }
        else {
            $content = Get-Content -LiteralPath $fullPath -Raw
            $null = $content | ConvertFrom-Json
            "JSON valide, $($item.Length) octets."
        }
    }
}

Invoke-ValidationCheck -Name "Topics Kafka payments, clicks et cart-events" -Action {
    $result = Invoke-ComposeCommand -Arguments @(
        "exec", "-T", "kafka",
        "/opt/kafka/bin/kafka-topics.sh",
        "--bootstrap-server", "kafka:19092", "--list"
    )
    Assert-NativeSuccess -Result $result -Label "Liste des topics Kafka"
    $topics = @($result.StdOut -split "\r?\n" | ForEach-Object { $_.Trim() })
    $expectedTopics = @("payments", "clicks", "cart-events")
    $missingTopics = @($expectedTopics | Where-Object { $_ -notin $topics })
    if ($missingTopics.Count -gt 0) {
        throw "Topics absents : $($missingTopics -join ', ')"
    }
    "Topics payments, clicks et cart-events disponibles."
}

Invoke-ValidationCheck -Name "Airflow possède une exécution réussie" -Action {
    $jsonResult = Invoke-ComposeCommand -Arguments @(
        "exec", "-T", "airflow", "airflow", "dags", "list-runs",
        "-d", $DagId, "--output", "json"
    )
    if (($jsonResult.ExitCode -eq 0) -and (-not [string]::IsNullOrWhiteSpace($jsonResult.StdOut))) {
        try {
            $runs = @($jsonResult.StdOut | ConvertFrom-Json)
            $successfulRuns = @($runs | Where-Object { $_.state -eq "success" })
            if ($successfulRuns.Count -gt 0) {
                return "$($successfulRuns.Count) exécution(s) réussie(s) pour $DagId."
            }
        }
        catch {
            # Si le JSON n'est pas disponible, le format tableau sera vérifié.
        }
    }
    $tableResult = Invoke-ComposeCommand -Arguments @(
        "exec", "-T", "airflow", "airflow", "dags", "list-runs", "-d", $DagId
    )
    Assert-NativeSuccess -Result $tableResult -Label "Airflow dags list-runs"
    if ($tableResult.StdOut -notmatch "(?im)(?:^|\|)\s*success\s*(?:\||$)") {
        throw "Aucune exécution Airflow réussie n'a été trouvée."
    }
    "Au moins une exécution réussie pour $DagId."
}

$cassandraTables = @(
    "product_metrics",
    "product_click_metrics",
    "cart_events",
    "product_cart_metrics",
    "batch_product_metrics",
    "batch_daily_sales",
    "batch_weekly_sales",
    "batch_monthly_sales"
)

foreach ($table in $cassandraTables) {
    Invoke-ValidationCheck -Name "Cassandra - kubeshop_analytics.$table" -Action {
        $query = "SELECT * FROM kubeshop_analytics.$table LIMIT 1;"
        $result = Invoke-ComposeCommand -Arguments @(
            "exec", "-T", "cassandra", "cqlsh", "-e", $query
        )
        Assert-NativeSuccess -Result $result -Label "Requête Cassandra sur $table"
        $combinedOutput = "$($result.StdOut)`n$($result.StdErr)"
        if ($combinedOutput -match "(?i)(InvalidRequest|SyntaxException|Unauthorized|AuthenticationFailed|NoHostAvailable|Traceback|Connection error)") {
            throw "Cassandra a signalé une erreur : $combinedOutput"
        }
        "Table accessible et requête SELECT réussie."
    }
}

Invoke-ValidationCheck -Name "Cohérence Batch jour, semaine et mois" -Action {
    $periodFiles = [ordered]@{
        jour = "data/output/daily_sales.csv"
        semaine = "data/output/weekly_sales.csv"
        mois = "data/output/monthly_sales.csv"
    }
    $totals = @{}

    foreach ($period in $periodFiles.Keys) {
        $rows = @(Import-Csv -LiteralPath (
            Join-Path $repoRoot $periodFiles[$period]
        ))
        $orders = [long]0
        $units = [long]0
        $revenue = [decimal]0

        foreach ($row in $rows) {
            $orders += [long]$row.orders_count
            $units += [long]$row.units_sold
            $revenue += [decimal]::Parse(
                [string]$row.total_revenue,
                [Globalization.CultureInfo]::InvariantCulture
            )
        }

        $totals[$period] = [pscustomobject]@{
            Orders = $orders
            Units = $units
            Revenue = $revenue
        }
    }

    foreach ($period in @("semaine", "mois")) {
        if (
            $totals[$period].Orders -ne $totals.jour.Orders -or
            $totals[$period].Units -ne $totals.jour.Units -or
            $totals[$period].Revenue -ne $totals.jour.Revenue
        ) {
            throw "Les totaux $period ne correspondent pas aux totaux quotidiens."
        }
    }

    $formattedRevenue = $totals.jour.Revenue.ToString(
        "0.00",
        [Globalization.CultureInfo]::InvariantCulture
    )
    "Totaux cohérents : $($totals.jour.Orders) commandes, " +
        "$($totals.jour.Units) unités et $formattedRevenue CAD."
}

Write-Host "`nRésumé de validation" -ForegroundColor Cyan
$results | Format-Table Statut, Test, Details -AutoSize -Wrap | Out-Host
$passedCount = @($results | Where-Object Statut -eq "PASS").Count
$failedCount = @($results | Where-Object Statut -eq "FAIL").Count
Write-Host "Réussis : $passedCount | Échecs : $failedCount"

if ($failedCount -gt 0) {
    Write-Host "Validation globale échouée." -ForegroundColor Red
    exit 1
}

Write-Host "Validation globale réussie." -ForegroundColor Green
exit 0
