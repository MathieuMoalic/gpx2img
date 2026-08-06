{
  description = "Development shell for gpx2img";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          pythonEnv = pkgs.python312.withPackages (ps: with ps; [
            pip
            pytest
            gpxpy
            fastapi
            uvicorn
            python-multipart
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              pythonEnv
              jdk
              osmium-tool
              just
              zip
              unzip
            ];
          };
        });
    };
}
