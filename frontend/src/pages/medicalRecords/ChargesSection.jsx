import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../../components/icons";
import SearchSelect from "../../components/SearchSelect";
import styles from "./consultationForm.module.css";

/**
 * Sección "Cargos" (presentacional): insumos/productos (toggle Insumo|Cobrar
 * por línea) + servicios profesionales + resumen con total en MXN calculado en
 * vivo desde el estado local. Cantidades, precios y totales en monoespaciada.
 *
 * Productos y servicios requieren que la consulta esté persistida (recordReady):
 * el container ya garantiza el guardado del borrador vía autosave, pero se
 * muestra un aviso mientras tanto.
 */
export default function ChargesSection({
  recordReady,
  disabled,
  productMap,
  fmtMXN,
  // productos
  productLine,
  onProductLineChange,
  onAddProduct,
  addedProducts,
  onRemoveProduct,
  onProductSearch,
  // servicios
  serviceLine,
  onServiceLineChange,
  onAddService,
  addedServices,
  onRemoveService,
  onServiceSearch,
  // totales (en vivo)
  productsTotal,
  servicesTotal,
  grandTotal,
}) {
  const selProd = productLine.product ? productMap[productLine.product.id] : null;
  const presentations = selProd?.presentations || [];
  const selPres = productLine.presentation;
  const selUnit =
    selPres?.base_unit_display || selPres?.base_unit || selProd?.base_unit || null;

  return (
    <motion.section
      className={styles.section}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.1 }}
    >
      <div className={styles.secHead}>
        <div className={styles.secIcon}>
          <Icon.Receipt s={17} />
        </div>
        <div className={styles.secTitleRow}>
          <h2 className={styles.secTitle}>Cargos</h2>
          {!recordReady && !disabled && (
            <span className={styles.secHint}>· se habilita al guardar el borrador</span>
          )}
        </div>
      </div>

      <div className={styles.grid2}>
        {/* ── Productos ── */}
        <div className={styles.field}>
          <label className={styles.fieldLabel}>
            Insumos / productos
            <span className="badge badge-warning" style={{ flexShrink: 0 }}>
              Puede cobrar
            </span>
          </label>
          <p className={styles.note}>
            <strong>Insumo</strong> descuenta inventario sin cobrar (gasas,
            jeringas). <strong>Cobrar</strong> descuenta y genera cargo.
          </p>

          {!disabled && (
            <div className={styles.adder}>
              <div style={{ marginBottom: 9 }}>
                <span className={styles.adderLabel}>Producto</span>
                <SearchSelect
                  placeholder="Buscar producto…"
                  value={productLine.product}
                  onChange={(item) => {
                    const prod = item ? productMap[item.id] : null;
                    onProductLineChange({
                      product: item,
                      presentation: prod?.presentations?.[0] ?? null,
                    });
                  }}
                  onSearch={onProductSearch}
                />
              </div>

              {selProd && presentations.length > 0 && (
                <div className={styles.presentationRow}>
                  <span className={styles.adderLabel} style={{ marginBottom: 0 }}>
                    Forma de venta
                  </span>
                  <select
                    className="input"
                    value={selPres?.id ?? ""}
                    onChange={(e) => {
                      const p =
                        presentations.find((x) => String(x.id) === e.target.value) || null;
                      onProductLineChange({ presentation: p });
                    }}
                  >
                    {presentations.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {fmtMXN(p.sale_price)}
                        {p.base_unit_display ? ` · ${p.base_unit_display}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.addGrid} style={{ marginTop: 9 }}>
                <div className={styles.costToggle}>
                  <button
                    type="button"
                    className={`${styles.costToggleBtn} ${
                      productLine.cost_behavior === "included"
                        ? styles.costToggleBtnActive
                        : ""
                    }`}
                    onClick={() => onProductLineChange({ cost_behavior: "included" })}
                  >
                    Insumo
                  </button>
                  <button
                    type="button"
                    className={`${styles.costToggleBtn} ${
                      productLine.cost_behavior === "charge"
                        ? styles.costToggleBtnActive
                        : ""
                    }`}
                    onClick={() => onProductLineChange({ cost_behavior: "charge" })}
                  >
                    Cobrar
                  </button>
                </div>
                <div className="cell" style={{ flex: "0 1 80px" }}>
                  <span className={styles.adderLabel}>Cant.</span>
                  <input
                    type="number"
                    min="1"
                    className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                    value={productLine.quantity}
                    title={selUnit ? `Cantidad en ${selUnit}` : "Cantidad"}
                    placeholder={selUnit ? `cant. ${selUnit}` : "1"}
                    onChange={(e) => onProductLineChange({ quantity: e.target.value })}
                  />
                </div>
                <button
                  className="btn btn-primary btn-md"
                  style={{ height: "38px" }}
                  onClick={onAddProduct}
                  disabled={!recordReady || !productLine.product || !productLine.presentation}
                >
                  Agregar
                </button>
              </div>
            </div>
          )}

          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Producto</th>
                  <th>Cant.</th>
                  <th>Facturación</th>
                  <th aria-label="acciones" />
                </tr>
              </thead>
              <tbody>
                {addedProducts.length === 0 ? (
                  <tr>
                    <td colSpan="4" className={styles.tableEmpty}>
                      Sin productos registrados
                    </td>
                  </tr>
                ) : (
                  <AnimatePresence initial={false}>
                    {addedProducts.map((p) => (
                      <motion.tr
                        key={p.id}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.18 }}
                      >
                        <td>
                          <div className={styles.cellName}>{p.product_name}</div>
                          <div className={styles.cellSub}>{p.presentation_name}</div>
                        </td>
                        <td className={styles.mono}>{p.quantity}</td>
                        <td>
                          {p.cost_behavior === "included" ? (
                            <span className={styles.badgeIncluido}>Insumo</span>
                          ) : (
                            <span className={styles.mono}>
                              {fmtMXN(Number(p.unit_price) * Number(p.quantity))}
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {!disabled && (
                            <button
                              className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`}
                              onClick={() => onRemoveProduct(p.id)}
                            >
                              <Icon.Trash s={14} />
                            </button>
                          )}
                        </td>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Servicios ── */}
        <div className={styles.field}>
          <label className={styles.fieldLabel}>
            Servicios profesionales
            <span className="badge badge-warning" style={{ flexShrink: 0 }}>
              Se cobra
            </span>
          </label>
          <p className={styles.note}>
            Honorarios y procedimientos. Siempre generan cargo.
          </p>

          {!disabled && (
            <div className={styles.adder}>
              <div style={{ marginBottom: 9 }}>
                <span className={styles.adderLabel}>Servicio</span>
                <SearchSelect
                  placeholder="Buscar servicio…"
                  value={serviceLine.service}
                  onChange={(item) => onServiceLineChange({ service: item })}
                  onSearch={onServiceSearch}
                />
              </div>
              <div className={styles.addGrid}>
                <div className="cell" style={{ flex: "0 1 80px" }}>
                  <span className={styles.adderLabel}>Cant.</span>
                  <input
                    type="number"
                    min="1"
                    className={`${styles.control} ${styles.miniInput} ${styles.mono}`}
                    value={serviceLine.quantity}
                    onChange={(e) => onServiceLineChange({ quantity: e.target.value })}
                  />
                </div>
                <button
                  className="btn btn-primary btn-md"
                  style={{ height: "38px", marginLeft: "auto" }}
                  onClick={onAddService}
                  disabled={!recordReady || !serviceLine.service}
                >
                  Agregar
                </button>
              </div>
            </div>
          )}

          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Servicio</th>
                  <th>Cant.</th>
                  <th>P. unit.</th>
                  <th>Subtotal</th>
                  <th aria-label="acciones" />
                </tr>
              </thead>
              <tbody>
                {addedServices.length === 0 ? (
                  <tr>
                    <td colSpan="5" className={styles.tableEmpty}>
                      Sin servicios registrados
                    </td>
                  </tr>
                ) : (
                  <AnimatePresence initial={false}>
                    {addedServices.map((s) => (
                      <motion.tr
                        key={s.id}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.18 }}
                      >
                        <td>
                          <div className={styles.cellName}>{s.name}</div>
                        </td>
                        <td className={styles.mono}>{s.quantity}</td>
                        <td className={styles.mono}>{fmtMXN(s.price)}</td>
                        <td className={styles.mono}>
                          {fmtMXN(Number(s.price) * Number(s.quantity))}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {!disabled && (
                            <button
                              className={`btn btn-ghost btn-xs ${styles.iconBtnDanger}`}
                              onClick={() => onRemoveService(s.id)}
                            >
                              <Icon.Trash s={14} />
                            </button>
                          )}
                        </td>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ── Resumen ── */}
      <div className={styles.resumen}>
        <div className={styles.resumenBox}>
          <div className={styles.resumenLine}>
            <span>Productos (cobrar)</span>
            <span className={styles.mono}>{fmtMXN(productsTotal)}</span>
          </div>
          <div className={styles.resumenLine}>
            <span>Servicios</span>
            <span className={styles.mono}>{fmtMXN(servicesTotal)}</span>
          </div>
          <div className={styles.resumenTotal}>
            <b>Total a cobrar</b>
            <span className={`${styles.resumenTotalVal} ${styles.mono}`}>
              {fmtMXN(grandTotal)}
            </span>
          </div>
        </div>
      </div>
    </motion.section>
  );
}
