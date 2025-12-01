Name:           hungryipscanner
Version:        1.0
Release:        2%{?dist}
Summary:        A simple utility for scanning IP addresses over the local network
License:        MIT
URL:            https://github.com/JulienGrdn/hungryipscanner
Source0:        %{url}/archive/main.tar.gz

BuildArch:      noarch

# System dependencies
Requires:       python3
Requires:       gtk4
Requires:       libadwaita
Requires:       python3-gobject
Requires:       hicolor-icon-theme

%description
Hungry IP Scanner is a simple utility for scanning IP addresses over the local
network. It provides a GUI built with GTK 4 and Libadwaita to display active
hosts on the network.

%prep
# NOTE: Ensure this matches your GitHub repo casing (hungryipscanner vs HungryIPScanner)
%autosetup -n hungryipscanner-main

%build
# Nothing to build for a pure Python script

%install
# 1. Install the main script with EXECUTABLE permissions (This fixes your error)
mkdir -p %{buildroot}%{_bindir}
install -m 0755 hungryip.py %{buildroot}%{_bindir}/hungryipscanner

# 2. Install the icon
# We verify the source filename is 'hungryipscannerlogo.svg' and rename it to standard 'hungryipscanner.svg'
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 hungryipscannerlogo.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/hungryipscanner.svg

# 3. Create a Desktop Entry manually
# This ensures Exec and Icon names match exactly what we installed above
mkdir -p %{buildroot}%{_datadir}/applications
cat > %{buildroot}%{_datadir}/applications/hungryipscanner.desktop <<EOF
[Desktop Entry]
Name=Hungry IP Scanner
Comment=Scan local network for active hosts
Exec=hungryipscanner
Icon=hungryipscanner
Terminal=false
Type=Application
Categories=Utility;Network;GTK;
StartupWMClass=hungryipscanner
StartupNotify=true
EOF

%files
%license LICENSE
%doc README.md
%{_bindir}/hungryipscanner
%{_datadir}/applications/hungryipscanner.desktop
%{_datadir}/icons/hicolor/scalable/apps/hungryipscanner.svg

%changelog
* Mon Dec 01 2025 Julien Grondin - 1.0-2
