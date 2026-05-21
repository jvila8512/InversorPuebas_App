namespace InverterMonWindow;

partial class Main
{
    private System.ComponentModel.IContainer components = null;

    protected override void Dispose(bool disposing)
    {
        if (disposing && (components != null))
        {
            components.Dispose();
        }
        base.Dispose(disposing);
    }

    /// <summary>
    /// Required method for Designer support - do not modify
    /// the contents of this method with the code editor.
    /// </summary>
    private void InitializeComponent()
    {
        components = new System.ComponentModel.Container();
        System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(Main));
        web = new Microsoft.Web.WebView2.WinForms.WebView2();
        TrayIcon = new System.Windows.Forms.NotifyIcon(components);
        ((System.ComponentModel.ISupportInitialize)web).BeginInit();
        SuspendLayout();

        //
        // web
        //
        web.AllowExternalDrop = false;
        web.Anchor = ((System.Windows.Forms.AnchorStyles)(((System.Windows.Forms.AnchorStyles.Top | System.Windows.Forms.AnchorStyles.Bottom) | System.Windows.Forms.AnchorStyles.Left) | System.Windows.Forms.AnchorStyles.Right));
        web.CreationProperties = null;
        web.DefaultBackgroundColor = System.Drawing.Color.White;
        web.Location = new System.Drawing.Point(-1, 1);
        web.Name = "web";
        web.Size = new System.Drawing.Size(642, 540);
        web.Source = new System.Uri("http://inverter.djnitehawk.com", System.UriKind.Absolute);
        web.TabIndex = 0;
        web.ZoomFactor = 1D;

        //
        // TrayIcon
        //
        TrayIcon.Icon = ((System.Drawing.Icon)resources.GetObject("TrayIcon.Icon"));
        TrayIcon.Text = "TrayIcon";

        //
        // Main
        //
        AutoScaleDimensions = new System.Drawing.SizeF(7F, 17F);
        AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
        BackColor = System.Drawing.SystemColors.Desktop;
        ClientSize = new System.Drawing.Size(639, 542);
        Controls.Add(web);
        FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        ShowIcon = false;
        ShowInTaskbar = false;
        StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
        Text = "InverterMon Window";
        TopMost = true;
        TransparencyKey = System.Drawing.Color.FromArgb(((int)((byte)0)), ((int)((byte)0)), ((int)((byte)64)));
        ((System.ComponentModel.ISupportInitialize)web).EndInit();
        ResumeLayout(false);
    }

    private Microsoft.Web.WebView2.WinForms.WebView2 web;
    private NotifyIcon TrayIcon;
}