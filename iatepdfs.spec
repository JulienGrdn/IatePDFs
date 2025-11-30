Name:           iatepdfs
Version:        1.0
Release:        1%{?dist}
Summary:        A modern GTK4 application for PDF manipulation
License:        MIT
URL:            https://github.com/JulienGrdn/IatePDFs
Source0:        %{url}/archive/main.tar.gz

BuildArch:      noarch

# System dependencies
Requires:       python3
Requires:       gtk4
Requires:       libadwaita
Requires:       python3-gobject
Requires:       ghostscript
Requires:       poppler-utils

# Python libraries available in Fedora
Requires:       python3-pypdf
Requires:       python3-pdf2image

%description
I ate PDFs is a modern, user-friendly GTK4 application for manipulating PDF
files on Linux. It features an intuitive drag-and-drop interface to merge,
compress, split, and reorder PDF documents.

%prep
%autosetup -n IatePDFs-main

%build
# Nothing to build for a pure Python script

%install
# 1. Install the main script
mkdir -p %{buildroot}%{_bindir}
install -m 0755 IAtePDFs.py %{buildroot}%{_bindir}/iatepdfs

# 2. Install the icon
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 IatePDFs.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/iatepdfs.svg

# 3. Create a Desktop Entry so it appears in the App Menu
mkdir -p %{buildroot}%{_datadir}/applications
cat > %{buildroot}%{_datadir}/applications/iatepdfs.desktop <<EOF
[Desktop Entry]
Name=I ate PDFs
Comment=Merge, compress, and split PDFs
Exec=iatepdfs
Icon=iatepdfs
Terminal=false
Type=Application
Categories=Utility;Office;GTK;
StartupWMClass=com.github.juliengrdn.iatepdfs
StartupNotify=true
EOF

%files
%license LICENSE
%doc README.md
%{_bindir}/iatepdfs
%{_datadir}/applications/iatepdfs.desktop
%{_datadir}/icons/hicolor/scalable/apps/iatepdfs.svg

%changelog
* Fri Nov 28 2024 JulienGrdn - 1.0-1
- Initial packaging for Copr
