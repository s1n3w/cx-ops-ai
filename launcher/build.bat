@echo off
rem Builds "CX Ops AI.exe" in the project folder with the C# compiler built into Windows.
cd /d "%~dp0"
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /out:"..\CX Ops AI.exe" Launcher.cs
