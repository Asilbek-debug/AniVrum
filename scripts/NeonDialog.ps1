function Read-NeonUrl {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    try {
        $form.Text = 'AniVrum - Neon tekshiruvi'
        $form.ClientSize = New-Object System.Drawing.Size(520, 130)
        $form.StartPosition = 'CenterScreen'
        $form.FormBorderStyle = 'FixedDialog'
        $form.MaximizeBox = $false
        $form.MinimizeBox = $false

        $label = New-Object System.Windows.Forms.Label
        $label.SetBounds(12, 14, 495, 20)
        $label.Text = "To‘liq Neon URL: Ctrl+V yoki Joylashtirish tugmasi."
        $field = New-Object System.Windows.Forms.TextBox
        $field.SetBounds(12, 42, 495, 24)
        $field.UseSystemPasswordChar = $true
        $field.ShortcutsEnabled = $true

        $paste = New-Object System.Windows.Forms.Button
        $paste.SetBounds(12, 82, 125, 30)
        $paste.Text = 'Joylashtirish'
        $paste.Add_Click({
            $field.Focus() | Out-Null
            $field.SelectAll()
            $field.Paste()
        })
        $submit = New-Object System.Windows.Forms.Button
        $submit.SetBounds(295, 82, 100, 30)
        $submit.Text = 'Tekshirish'
        $submit.DialogResult = 'OK'
        $cancel = New-Object System.Windows.Forms.Button
        $cancel.SetBounds(407, 82, 100, 30)
        $cancel.Text = 'Bekor qilish'
        $cancel.DialogResult = 'Cancel'
        $form.Controls.AddRange(@($label, $field, $paste, $submit, $cancel))
        $form.AcceptButton = $submit
        $form.CancelButton = $cancel
        $form.ActiveControl = $field
        if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK -or $field.TextLength -eq 0) {
            return $null
        }
        return ConvertTo-SecureString -String $field.Text -AsPlainText -Force
    } finally {
        if ($null -ne $field) { $field.Clear() }
        $form.Dispose()
    }
}
