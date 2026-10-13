param([Parameter(Mandatory=$true)][string]$LiteralPath)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $LiteralPath
$versionInfo = (Get-Item -LiteralPath $LiteralPath -ErrorAction Stop).VersionInfo
$signatureCommand = Get-Command -Name Get-AuthenticodeSignature -CommandType Cmdlet -ListImported -ErrorAction Stop
@{
    status = $signature.Status.ToString()
    subject = $signature.SignerCertificate.Subject
    thumbprint = $signature.SignerCertificate.Thumbprint
    original_filename = $versionInfo.OriginalFilename
    product_name = $versionInfo.ProductName
    file_version = $versionInfo.FileVersion
    powershell = @{
        version = $PSVersionTable.PSVersion.ToString()
        edition = $PSVersionTable.PSEdition
        home = $PSHOME
        signature_cmdlet_module_path = $signatureCommand.Module.Path
    }
} | ConvertTo-Json -Depth 4 -Compress
