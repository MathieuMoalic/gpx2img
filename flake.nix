{
  description = "gpx2img with Nix package and bundled mkgmap.jar";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = {self, nixpkgs, ...}: let
    systems = ["x86_64-linux"];
    forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs {inherit system;}));
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
  };
}
