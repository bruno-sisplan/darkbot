// Lançador do darkbot: um .exe só, que abre rápido.
//
// O app (Python + Playwright, ~150 MB descompactado) vai dentro deste .exe como um zip. Na primeira vez ele é
// descompactado em %LOCALAPPDATA%\darkbot\app\<versão> (com uma janelinha "Preparando o darkbot"); daí em diante
// o lançador só abre o app que já está lá, sem descompactar nada. Versão nova = pasta nova (a antiga é apagada).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("darkbot")]
[assembly: AssemblyProduct("darkbot")]
[assembly: AssemblyDescription("Radar de nichos dark do YouTube")]
[assembly: AssemblyVersion("__ASMVERSION__")]

static class Program
{
    const string VERSION = "__VERSION__";

    [STAThread]
    static void Main(string[] args)
    {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "darkbot", "app");
        string dir = Path.Combine(root, VERSION);
        string exe = Path.Combine(dir, "darkbot.exe");

        if (!File.Exists(Path.Combine(dir, ".ok")) || !File.Exists(exe))
        {
            Application.EnableVisualStyles();
            Exception error = null;
            var splash = new Splash();
            var worker = new Thread(() =>
            {
                try { Extract(root, dir); }
                catch (Exception e) { error = e; }
                splash.BeginInvoke(new Action(splash.Close));
            });
            splash.Shown += (s, e) => worker.Start();
            Application.Run(splash);
            if (error != null)
            {
                MessageBox.Show("Não consegui preparar o darkbot:\n\n" + error.Message, "darkbot",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
        }

        string argline = "";
        foreach (var a in args) argline += (argline.Length > 0 ? " " : "") + "\"" + a.Replace("\"", "\\\"") + "\"";
        Process.Start(new ProcessStartInfo(exe, argline) { WorkingDirectory = dir, UseShellExecute = false });
    }

    static void Extract(string root, string dir)
    {
        string tmp = dir + ".tmp";
        if (Directory.Exists(tmp)) Directory.Delete(tmp, true);
        Directory.CreateDirectory(tmp);
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
        {
            zip.ExtractToDirectory(tmp);
        }
        if (Directory.Exists(dir)) Directory.Delete(dir, true);
        Directory.Move(tmp, dir);
        File.WriteAllText(Path.Combine(dir, ".ok"), VERSION);
        // Apaga versões antigas (se alguma estiver aberta, fica para a próxima).
        foreach (string old in Directory.GetDirectories(root))
        {
            if (string.Equals(old, dir, StringComparison.OrdinalIgnoreCase)) continue;
            try { Directory.Delete(old, true); } catch { }
        }
    }
}

class Splash : Form
{
    public Splash()
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(380, 130);
        BackColor = Color.FromArgb(18, 18, 20);
        ShowInTaskbar = true;
        Text = "darkbot";
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        var title = new Label
        {
            Text = "Preparando o darkbot…",
            ForeColor = Color.FromArgb(225, 225, 230),
            Font = new Font("Segoe UI Semibold", 13f),
            AutoSize = false, TextAlign = ContentAlignment.MiddleCenter,
            Bounds = new Rectangle(0, 30, 380, 32),
        };
        var sub = new Label
        {
            Text = "Só na primeira vez. Leva alguns segundos.",
            ForeColor = Color.FromArgb(153, 109, 255),
            Font = new Font("Segoe UI", 9.5f),
            AutoSize = false, TextAlign = ContentAlignment.MiddleCenter,
            Bounds = new Rectangle(0, 66, 380, 24),
        };
        Controls.Add(title);
        Controls.Add(sub);
    }
}
