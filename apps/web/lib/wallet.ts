// Sign EIP-712 typed data with the injected wallet (MetaMask). Returns the signature and signing address.
export async function signTypedData(typed_data: any): Promise<{ signature: string; from: string }> {
  const eth = (window as any).ethereum;
  if (!eth) throw new Error("MetaMask not found");
  const accounts = await eth.request({ method: "eth_requestAccounts" });
  const from = accounts[0];
  // MetaMask refuses to sign typed data whose domain chainId differs from the active chain
  const chainHex = "0x" + Number(typed_data.domain.chainId).toString(16);
  if ((await eth.request({ method: "eth_chainId" })) !== chainHex) {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainHex }] });
  }
  const signature = await eth.request({
    method: "eth_signTypedData_v4",
    params: [from, JSON.stringify(typed_data)],
  });
  return { signature, from };
}
