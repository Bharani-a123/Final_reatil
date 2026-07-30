/*
 * SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from "react";
import { ApparelProps } from "../types";
import { getDefaultImage } from "../config/config";

const Apparel: React.FC<ApparelProps> = ({ newRenderImage, retrievedProducts = [], isCartView = false, onRemoveProduct }) => {
  const displayImage = newRenderImage || getDefaultImage();

  return (
    <div
      style={{ width: "40vw", padding: "24px", boxSizing: "border-box" }}
      className="flex flex-col bg-[#F9F9F9] border-r border-gray-200 h-[85vh] overflow-y-auto"
    >
      {retrievedProducts.length > 0 ? (
        <div className="flex flex-col w-[100%] gap-4">
          <h2 className="text-[20px] font-bold text-[#202020] mb-2 border-b pb-2 flex items-center justify-between">
            <span>{isCartView ? "Your Shopping Cart" : "Requested Catalog Items"}</span>
            {isCartView && (
              <span className="text-[14px] font-normal text-gray-500">
                ({retrievedProducts.length} {retrievedProducts.length === 1 ? "item" : "items"})
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {retrievedProducts.map((product, idx) => (
              <div 
                key={idx} 
                className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col p-3 hover:shadow-md transition-all duration-200"
              >
                <div className="w-[100%] h-[180px] overflow-hidden rounded-md bg-gray-50 flex items-center justify-center mb-2 relative group">
                  <img
                    src={product.productUrl}
                    alt={product.productName}
                    className="max-h-[100%] max-w-[100%] object-contain transition-transform duration-300 group-hover:scale-105"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = getDefaultImage();
                    }}
                  />
                </div>
                <div className="text-[14px] font-bold text-[#202020] line-clamp-2 min-h-[40px] flex-grow">
                  {product.productName}
                </div>
                {isCartView && onRemoveProduct && (
                  <button
                    onClick={() => onRemoveProduct(product.productName)}
                    className="mt-3 w-full py-2 bg-[#ff4d4f] hover:bg-[#e03d3e] text-white text-[13px] font-bold rounded-md transition-colors duration-200 flex items-center justify-center gap-1.5 shadow-sm active:scale-95 transform"
                  >
                    <span className="text-[14px]">🗑️</span> Remove Item
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex w-[100%] h-[100%] items-center justify-center overflow-hidden object-contain">
          <img
            src={displayImage}
            alt="Product display"
            className="product-image max-h-[100%] max-w-[100%] object-contain"
          />
        </div>
      )}
    </div>
  );
};

export default Apparel;
