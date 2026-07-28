<#
    run.ps1 -- replaces the Makefile.

    `make` is a Unix build tool and is not installed on this machine. The
    old Makefile also used bash `until ... sleep` loops, which will not run
    on Windows. This script does the same jobs in PowerShell.

    Usage:
        .\run.ps1 up            start Neo4j and wait until it answers
        .\run.ps1 down          stop Neo4j (data is kept in volumes)
        .\run.ps1 schema        apply constraints + indexes
        .\run.ps1 verify        Phase 0 definition of done
        .\run.ps1 counts        node count per label
        .\run.ps1 logs          tail the Neo4j container log
        .\run.ps1 browser       open Neo4j Browser
        .\run.ps1 nuke          DELETE ALL DATA and start clean

    Every command is a thin wrapper. If you prefer, run the underlying
    commands directly -- there is no magic here.
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'schema', 'verify', 'counts', 'logs', 'browser', 'nuke')]
    [string]$Command = 'verify'
)

$ErrorActionPreference = 'Stop'
$Container = 'neo4j_semantic_seo'
$Password  = 'password123'

function Assert-Docker {
    docker info *> $null
    if (-not $?) {
        Write-Host ""
        Write-Host "Docker is not responding." -ForegroundColor Red
        Write-Host "Start Docker Desktop from the Start menu, wait for the whale"
        Write-Host "icon in the system tray to stop animating, then retry."
        Write-Host ""
        exit 1
    }
}

switch ($Command) {

    'up' {
        Assert-Docker
        docker compose up -d
        if (-not $?) { exit 1 }

        Write-Host ""
        Write-Host "Waiting for Neo4j to accept connections..." -ForegroundColor Cyan
        Write-Host "(first boot downloads the APOC and GDS plugins -- allow 1-2 min)"

        $deadline = (Get-Date).AddMinutes(5)
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            docker exec $Container cypher-shell -u neo4j -p $Password 'RETURN 1;' *> $null
            if ($?) { $ready = $true; break }
            Write-Host "  ..still starting" -ForegroundColor DarkGray
            Start-Sleep -Seconds 5
        }

        if ($ready) {
            Write-Host ""
            Write-Host "Neo4j is up." -ForegroundColor Green
            Write-Host "  Browser: http://localhost:7474   (neo4j / $Password)"
            Write-Host "  Bolt:    bolt://localhost:7687"
            Write-Host ""
            Write-Host "Next:  .\run.ps1 schema"
        } else {
            Write-Host ""
            Write-Host "Timed out after 5 minutes." -ForegroundColor Red
            Write-Host "Check the logs:  .\run.ps1 logs"
            exit 1
        }
    }

    'down' {
        docker compose down
        Write-Host "Stopped. Data is preserved in Docker volumes." -ForegroundColor Green
    }

    'schema'  { python -m src.db --init-schema }
    'verify'  { python -m src.db --verify }
    'counts'  { python -m src.db --counts }
    'logs'    { docker compose logs -f --tail 100 neo4j }
    'browser' { Start-Process 'http://localhost:7474' }

    'nuke' {
        Write-Host ""
        Write-Host "This DELETES the database volume. All nodes, all data, gone." -ForegroundColor Yellow
        $answer = Read-Host "Type 'yes' to confirm"
        if ($answer -ne 'yes') { Write-Host "Cancelled."; exit 0 }
        docker compose down -v
        Write-Host "Volumes removed. Run '.\run.ps1 up' to start clean." -ForegroundColor Green
    }
}
