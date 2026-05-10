import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  { ignores: ["components/ui/**"] },
  ...coreWebVitals,
  ...typescript,
];

export default config;
