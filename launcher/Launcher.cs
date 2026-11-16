// "CX Ops AI.exe": runs the interactive app with the project's virtual environment.
// Build with launcher\build.bat (uses the C# compiler that ships with Windows).
using System;
using System.Diagnostics;
using System.IO;

class Launcher
{
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python))
        {
            Console.WriteLine("Can't find " + python);
            Console.WriteLine("Set up the project first (see README: Run it). Press Enter to close.");
            Console.ReadLine();
            return 1;
        }
        var info = new ProcessStartInfo(python, "-m cxops.app") { WorkingDirectory = root, UseShellExecute = false };
        using (var p = Process.Start(info))
        {
            p.WaitForExit();
            if (p.ExitCode != 0)
            {
                Console.WriteLine("\nThe app stopped with an error (code " + p.ExitCode + "). Press Enter to close.");
                Console.ReadLine();
            }
            return p.ExitCode;
        }
    }
}
