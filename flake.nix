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
        buildInputs = with pkgs; [
          python312
          jdk
          osmium-tool
          just
          zip
          unzip
          uv
        ];

        shellHook = ''
          # Create .venv using uv (astral uv) and activate it
          if [ ! -d ".venv" ]; then
            echo "Creating virtual environment with uv..."
            uv venv --python ${pkgs.python312}/bin/python3 .venv
          fi
          uv sync --extra dev
          . .venv/bin/activate
        '';
      };
    };
}
