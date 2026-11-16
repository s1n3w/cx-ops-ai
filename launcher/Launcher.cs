// "CX Ops AI.exe": opens the desktop app (pythonw -m cxops.gui) with the project's virtual environment.
// No console window. Build with launcher\build.bat (uses the C# compiler that ships with Windows).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher
{
    [STAThread]
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show("Can't find " + pythonw + "\n\nSet up the project first (README: Run it).",
                            "CX Ops AI", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        Process.Start(new ProcessStartInfo(pythonw, "-m cxops.gui") { WorkingDirectory = root, UseShellExecute = false });
        return 0;
    }
}
