{
  description = "gpx2img with Nix package and bundled mkgmap.jar";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = {
    self,
    nixpkgs,
    ...
  }: let
    systems = ["x86_64-linux"];
    forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs {inherit system;}));
    nixosModule = {
      lib,
      config,
      pkgs,
      ...
    }: let
      cfg = config.services.gpx2img;
    in {
      options.services.gpx2img = {
        enable = lib.mkEnableOption "gpx2img web server";

        package = lib.mkOption {
          type = lib.types.package;
          default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
          description = "The gpx2img package to use.";
        };

        host = lib.mkOption {
          type = lib.types.str;
          default = "127.0.0.1";
          description = "Address the web server binds to.";
        };

        port = lib.mkOption {
          type = lib.types.port;
          default = 8000;
          description = "TCP port the web server listens on.";
        };

        user = lib.mkOption {
          type = lib.types.str;
          default = "gpx2img";
          description = "System user that runs the service.";
        };

        group = lib.mkOption {
          type = lib.types.str;
          default = "gpx2img";
          description = "System group that runs the service.";
        };

        openFirewall = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Open the configured port in the firewall.";
        };
      };

      config = lib.mkIf cfg.enable {
        users.users.${cfg.user} = {
          isSystemUser = true;
          group = cfg.group;
          home = "/var/lib/gpx2img";
          createHome = true;
        };

        users.groups.${cfg.group} = {};

        systemd.tmpfiles.rules = [
          "d /var/lib/gpx2img 0750 ${cfg.user} ${cfg.group} - -"
        ];

        systemd.services.gpx2img = {
          description = "gpx2img web server";
          after = ["network.target"];
          wantedBy = ["multi-user.target"];

          serviceConfig = {
            ExecStart = "${cfg.package}/bin/gpx2img-web --host ${cfg.host} --port ${toString cfg.port}";
            User = cfg.user;
            Group = cfg.group;
            WorkingDirectory = "/var/lib/gpx2img";
            Restart = "always";
            RestartSec = "5s";
            NoNewPrivileges = "yes";
            PrivateTmp = "yes";
            ProtectSystem = "strict";
            ReadWritePaths = ["/var/lib/gpx2img"];
          };
        };

        networking.firewall.allowedTCPPorts = lib.optionals cfg.openFirewall [cfg.port];
      };
    };
  in {
    packages = forAllSystems (pkgs: let
      python = pkgs.python312.override {
        packageOverrides = final: prev: {
          scipy = prev.scipy.overridePythonAttrs (_: {doCheck = false;});
          fastapi = prev.fastapi.overridePythonAttrs (_: {doCheck = false;});
          inline-snapshot = prev.inline-snapshot.overridePythonAttrs (_: {doCheck = false;});
        };
      };
      pyPkgs = python.pkgs;

      mkgmapJar = pkgs.stdenvNoCC.mkDerivation rec {
        pname = "mkgmap-jar";
        version = "r4924";
        src = pkgs.fetchurl {
          url = "https://www.mkgmap.org.uk/download/mkgmap-${version}.zip";
          hash = "sha256-shcHmbYaldT8JY6OT7TiE5aAngOQeJF4+Ux3EJ+ODYQ=";
        };
        nativeBuildInputs = [pkgs.unzip];
        dontUnpack = true;
        installPhase = ''
          runHook preInstall
          mkdir -p $out/share/mkgmap
          unzip -j "$src" "mkgmap-${version}/mkgmap.jar" -d $out/share/mkgmap
          runHook postInstall
        '';
      };

      gpx2img = pyPkgs.buildPythonApplication {
        pname = "gpx2img";
        version = "0.1.0";
        pyproject = true;
        src = ./.;
        build-system = [pyPkgs.hatchling];
        dependencies = with pyPkgs; [
          gpxpy
          fastapi
          uvicorn
          python-multipart
          httpx
          shapely
        ];
      };

      gpx2imgWithMkgmap = pkgs.symlinkJoin {
        name = "gpx2img-with-mkgmap";
        paths = [gpx2img];
        nativeBuildInputs = [pkgs.makeWrapper];
        postBuild = ''
          wrapProgram $out/bin/gpx2img \
            --set-default GPX2IMG_MKGMAP_JAR ${mkgmapJar}/share/mkgmap/mkgmap.jar \
            --prefix PATH : ${pkgs.lib.makeBinPath [pkgs.jdk pkgs.osmium-tool]}
          wrapProgram $out/bin/gpx2img-web \
            --set-default GPX2IMG_MKGMAP_JAR ${mkgmapJar}/share/mkgmap/mkgmap.jar \
            --prefix PATH : ${pkgs.lib.makeBinPath [pkgs.jdk pkgs.osmium-tool]}
        '';
      };
    in {
      default = gpx2imgWithMkgmap;
      gpx2img = gpx2imgWithMkgmap;
      mkgmap-jar = mkgmapJar;
    });

    apps = forAllSystems (pkgs: {
      default = {
        type = "app";
        program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/gpx2img-web";
      };
      web = {
        type = "app";
        program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/gpx2img-web";
      };
      gpx2img = {
        type = "app";
        program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.gpx2img}/bin/gpx2img";
      };
      cli = {
        type = "app";
        program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.gpx2img}/bin/gpx2img";
      };
    });

    devShells = forAllSystems (pkgs: {
      default = let
        python = pkgs.python312.override {
          packageOverrides = final: prev: {
            scipy = prev.scipy.overridePythonAttrs (_: {doCheck = false;});
            fastapi = prev.fastapi.overridePythonAttrs (_: {doCheck = false;});
            inline-snapshot = prev.inline-snapshot.overridePythonAttrs (_: {doCheck = false;});
          };
        };
        devPython = python.withPackages (ps:
          with ps; [
            pytest
            gpxpy
            fastapi
            uvicorn
            python-multipart
            httpx
            shapely
            starlette
          ]);
      in
        pkgs.mkShell {
          buildInputs = with pkgs; [
            devPython
            jdk
            osmium-tool
            just
            zip
            unzip
            qmapshack
          ];

          shellHook = ''
            export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
          '';
        };
    });

    nixosModules.gpx2img = nixosModule;
    nixosModules.gpx2img-service = nixosModule;
  };
}
