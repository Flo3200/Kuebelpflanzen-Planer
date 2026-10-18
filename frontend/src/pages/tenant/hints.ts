// Translated hints for unplanned stops and fixed teams (package D): {code, params} from the server.
import { t, tMaybe } from "../../i18n";

export function hintText(h: { code: string; params: Record<string, any> }): string {
  return tMaybe(`planning.hints.${h.code}`, h.params) ?? h.code;
}

export function reasonText(reason: string): string {
  return t(`planning.reasons.${reason}`);
}
