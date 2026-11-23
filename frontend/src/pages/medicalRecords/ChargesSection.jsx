import { forwardRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../../components/icons";
import SearchSelect from "../../components/SearchSelect";
import styles from "./consultationForm.module.css";

const ChargesSection = forwardRef(function ChargesSection({
  recordReady,
  disabled,
  productMap,
  fmtMXN,
  // productos
  productLine,
  productLots = [],
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
}, ref) {
  const selProd = productLine.product ? productMap[productLine.product.id] : null;
  const presentations = selProd?.presentations || [];
  const selPres = productLine.presentation;
  const selUnit =
    selPres?.base_unit_display || selPres?.base_unit || selProd?.base_unit || null;

  const [servicesOpen, setServicesOpen] = useState(false);

  return (
    <motion.section
      ref={ref}
      className={styles.card}
      data-consult-step="charges"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.1 }}
    >
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Cobros</h2>
        <p className={styles.cardDesc}>Productos, servicios y total a cobrar</p>
      </div>

      {!recordReady && !disabled && (
        <p className={styles.note} style={{ marginBottom: 16 }}>
          Los cobros se habilitan al guardar el borrador.
        </p>
      )}

          {/* ── Productos ── */}
          <div className={styles.field}>
            <label className={`${styles.fieldLabel} ${styles.fieldLabelMinimal}`}>Productos</label>
            <p className={styles.note}>
              Elige si cada producto se cobra o se registra solo como insumo interno.
            </p>

            {!disabled && (
              <div className={styles.adderLite}>
                <div style={{ marginBottom: 8 }}>
                  <span className={styles.adderLabel}>Producto</span>
                  <SearchSelect
                    placeholder="Buscar producto…"
                    value={productLine.product}
                    onChange={(item) => {
                      const prod = item ? productMap[item.id] : null;
                      onProductLineChange({
                        product: item,
                        presentation: prod?.presentations?.[0] ?? null,
                        lot: null,
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

                {selProd?.tracks_lots && (
                  <div className={styles.presentationRow}>
                    <span className={styles.adderLabel} style={{ marginBottom: 0 }}>
                      Lote (FEFO)
                    </span>
                    <select
                      className="input"
                      value={productLine.lot?.id ?? ""}
                      onChange={(e) => {
                        const l = productLots.find((x) => String(x.id) === e.target.value) || null;
                        onProductLineChange({ lot: l });
                      }}
                    >
                      {productLots.length === 0 && <option value="">Sin lotes disponibles</option>}
                      {productLots.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.lot_number}
                          {l.expiry_date ? ` · vence ${l.expiry_date}` : ""}
                          {" · "}
                          {Math.round(Number(l.quantity_on_hand))} disp.
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className={styles.addGrid} style={{ marginTop: 8 }}>
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
                    <Icon.Plus s={15} /> Agregar
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
                    <th>Modo</th>
                    <th>Subtotal</th>
                    <th aria-label="acciones" />
                  </tr>
                </thead>
                <tbody>
                  {addedProducts.length === 0 ? (
                    <tr>
                      <td colSpan="5" className={styles.tableEmpty}>
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
                              <span className={styles.tableModeMuted}>Insumo</span>
                            ) : (
                              <span className={styles.tableModeStrong}>Cobrar</span>
                            )}
                          </td>
                          <td className={styles.mono}>
                            {p.cost_behavior === "included"
                              ? "-"
                              : fmtMXN(Number(p.unit_price) * Number(p.quantity))}
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

          {/* ── Servicios toggle ── */}
          <button
            type="button"
            className={`${styles.serviceToggle} ${servicesOpen ? styles.serviceToggleOpen : ""}`}
            onClick={() => setServicesOpen(!servicesOpen)}
          >
            <span className={styles.serviceToggleIcon}>
              {servicesOpen ? <Icon.Minus s={14} /> : <Icon.Plus s={14} />}
            </span>
            <span>{servicesOpen ? "Cerrar servicios" : "¿Se realizó algún servicio?"}</span>
          </button>

          {servicesOpen && (
            <div className={styles.serviceSection}>
              <div className={styles.field}>
                <p className={styles.note}>
                  Honorarios y procedimientos registrados para esta atencion.
                </p>

                {!disabled && (
                  <div className={styles.adderLite}>
                    <div style={{ marginBottom: 8 }}>
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
                        <Icon.Plus s={15} /> Agregar servicio
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
          )}

    </motion.section>
  );
});

export default ChargesSection;
