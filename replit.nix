{ pkgs }: {
  deps = [
    pkgs.python312
    pkgs.nodejs_20
    pkgs.nodePackages.pnpm
    pkgs.postgresql_16 # psql client only -- Replit has no managed Postgres;
                        # DATABASE_URL must point at an external one (see README).
  ];
}
