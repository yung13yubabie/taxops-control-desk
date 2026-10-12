param([Parameter(Mandatory=$true)][string]$LiteralPath)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $LiteralPath
$signatureCommand = Get-Command -Name Get-AuthenticodeSignature -CommandType Cmdlet -ListImported -ErrorAction Stop
@{
    status = $signature.Status.ToString()
    subject = $signature.SignerCertificate.Subject
    thumbprint = $signature.SignerCertificate.Thumbprint
    powershell = @{
        version = $PSVersionTable.PSVersion.ToString()
        edition = $PSVersionTable.PSEdition
        home = $PSHOME
        signature_cmdlet_module_path = $signatureCommand.Module.Path
    }
} | ConvertTo-Json -Depth 4 -Compress
