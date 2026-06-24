import { PulseIcon } from "./icons/PulseIcon";

export function Brand() {
  return (
    <div className="brand" data-testid="brand-saaslyvet">
      <div className="brand-mark" aria-hidden="true">
        <PulseIcon size={22} color="#1a4434" />
      </div>
      <div className="brand-name">SaaslyVet</div>
    </div>
  );
}
