<#
.SYNOPSIS
  Stop sticky Docker MCP Toolkit containers and optional WP-CLI leftovers.

.DESCRIPTION
  Docker Desktop MCP gateway often leaves mcp/* containers running (especially
  node-code-sandbox). This script stops labeled docker-mcp containers and,
  optionally, abandoned wordpress:cli one-shots from compose run.

  Prefer routing catalog tools through Dynamic MCP Proxy (user.catalogue.json
  docker-mcp-* entries) and disable or lean-profile Cursor's MCP_DOCKER.

.PARAMETER IncludeWpCli
  Also stop running wordpress:cli containers (ellismediation compose leftovers).

.PARAMETER WhatIf
  Show what would be stopped without stopping.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeWpCli
)

$ErrorActionPreference = 'Stop'

function Get-DockerMcpIds {
    docker ps -q --filter 'label=docker-mcp=true'
}

function Get-WpCliIds {
    docker ps -q --filter 'ancestor=wordpress:cli-php8.3'
}

Write-Host '=== Before ==='
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Size}}' | Select-Object -First 40
$os = Get-CimInstance Win32_OperatingSystem
Write-Host ("FreeMB={0}" -f [math]::Round($os.FreePhysicalMemory / 1024, 0))

$mcpIds = @(Get-DockerMcpIds)
Write-Host ("docker-mcp containers: {0}" -f $mcpIds.Count)
if ($mcpIds.Count -gt 0) {
    docker ps --filter 'label=docker-mcp=true' --format '{{.Names}}  {{.Label "docker-mcp-name"}}  {{.Status}}'
    if ($PSCmdlet.ShouldProcess(("stop {0} docker-mcp containers" -f $mcpIds.Count), 'Stop')) {
        docker stop @mcpIds | Out-Host
        docker rm @mcpIds 2>$null | Out-Host
    }
}

if ($IncludeWpCli) {
    $wpIds = @(Get-WpCliIds)
    Write-Host ("wordpress:cli containers: {0}" -f $wpIds.Count)
    if ($wpIds.Count -gt 0) {
        docker ps --filter 'ancestor=wordpress:cli-php8.3' --format '{{.Names}}  {{.Status}}'
        if ($PSCmdlet.ShouldProcess(("stop {0} wordpress:cli containers" -f $wpIds.Count), 'Stop')) {
            docker stop @wpIds | Out-Host
            docker rm @wpIds 2>$null | Out-Host
        }
    }
}

Write-Host '=== After ==='
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | Select-Object -First 30
$os2 = Get-CimInstance Win32_OperatingSystem
Write-Host ("FreeMB={0}" -f [math]::Round($os2.FreePhysicalMemory / 1024, 0))
Write-Host 'Tip: Cursor MCP_DOCKER should use --profile hermes-lean or be disabled; activate docker-mcp-* via Dynamic MCP Proxy instead.'
