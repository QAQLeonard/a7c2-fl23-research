# Optional legacy wrapper. The two public CMD entries need no PowerShell.
$workflowArgs = @($args)
$entryName = 'FL23.cmd'
if ($workflowArgs.Count -gt 0 -and $workflowArgs[0] -eq 'looks') {
    $entryName = 'Custom-LUT.cmd'
    $workflowArgs = @($workflowArgs | Select-Object -Skip 1)
} elseif ($workflowArgs.Count -gt 0 -and $workflowArgs[0] -eq 'fl23') {
    $workflowArgs = @($workflowArgs | Select-Object -Skip 1)
}
& (Join-Path $PSScriptRoot ('..\..\' + $entryName)) @workflowArgs
exit $LASTEXITCODE
