{
  description = "Development shell for gpx2img";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = with pkgs; [
          python312
          jdk
          osmium-tool
          just
          zip
          unzip
        ];

        shellHook = ''
          # create and activate venv, then install Python deps into it
          if [ -z "${VIRTUAL_ENV-}" ]; then
            if [ ! -d .venv ]; then
              echo "Creating .venv and installing Python deps..."
              python -m venv .venv
              . .venv/bin/activate
              python -m pip install --upgrade pip
              pip install -e ".[dev]"
            else
              . .venv/bin/activate
            fi
          fi
        '';
      };
    };
}
